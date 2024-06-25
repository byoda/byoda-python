'''
Class PodServer derived from Server class for modelling
a server that hosts a BYODA Service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from uuid import UUID
from typing import TypeVar
from hashlib import sha256
from logging import getLogger

from byoda.datamodel.table import Table
from byoda.datamodel.content_key import ContentKey
from byoda.datamodel.content_key import RESTRICTED_CONTENT_KEYS_TABLE
from byoda.datamodel.app import App

from byoda.datatypes import ServerType
from byoda.datatypes import CloudType
from byoda.datatypes import IdType
from byoda.datatypes import CacheType
from byoda.datatypes import AppType

from byoda.secrets.account_secret import AccountSecret
from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.data_secret import DataSecret

from byoda.datastore.document_store import DocumentStoreType
from byoda.datastore.data_store import DataStoreType, DataStore
from byoda.datastore.cache_store import CacheStore

from byoda.storage.filestorage import FileStorage

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.restapi_client import RestApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.paths import Paths

from byoda.util.logger import Logger

from byoda import config

from .server import Server


_LOGGER: Logger = getLogger(__name__)


Network = TypeVar('Network')
RegistrationStatus = TypeVar('RegistrationStatus')
Member = TypeVar('Member')
Account = TypeVar('Account')
JWT = TypeVar('JWT')
YouTube = TypeVar('YouTube')


class PodServer(Server):
    HTTP_PORT = 8000

    def __init__(self, network: Network = None,
                 cloud_type: CloudType = CloudType.LOCAL,
                 bootstrapping: bool = False,
                 db_connection_string: str | None = None) -> None:
        '''
        Sets up data structures for a pod server

        :param network: The network this server is part of
        :param cloud_type: The cloud this server runs in
        :param bootstrapping: are we allowed to create secrets
        or database files from scratch when a download from
        object storage fails.
        '''

        super().__init__(network, cloud_type=cloud_type)

        self.server_type = ServerType.POD
        self.cloud: CloudType = cloud_type

        self.cdn_fqdn: str | None = None
        self.cdn_origin_site_id: str | None = None

        # TODO: don't believe we use self.service_summaries. We only use
        # (self.)network.service_summaries
        self.service_summaries: dict[int:dict[str, str | int | None]] = {}

        self.bootstrapping: bool = bootstrapping

        self.db_connection_string: str | None = db_connection_string
        self.data_store: DataStore | None = None
        self.cache_store: CacheStore | None = None

        self.account: Account | None = None

        self.apps: dict[UUID, App] = {}

        # These are used by the pod_worker for importing data
        self.youtube_client: YouTube | None = None

    async def load_secrets(self, password: str = None) -> None:
        '''
        Loads the secrets used by the podserver
        '''
        await self.account.load_secrets()

        # We use the account secret as client TLS cert for outbound
        # requests and as private key for the TLS server
        filepath: str = await self.account.tls_secret.save_tmp_private_key()

        config.requests.cert = (
            self.account.tls_secret.cert_file, filepath
        )

    async def get_registered_services(self) -> None:
        '''
        Downloads a list of service summaries
        '''

        network: Network = self.network

        url: str = network.paths.get(Paths.NETWORKSERVICES_API)
        resp: HttpResponse = await RestApiClient.call(url)

        network.service_summaries = {}
        if resp.status_code == 200:
            summaries = resp.json()
            for summary in summaries.get('service_summaries', []):
                service_id: int = summary['service_id']
                network.service_summaries[service_id] = summary

            _LOGGER.debug(
                f'Read summaries for {len(self.network.service_summaries)} '
                'services'
            )
        else:
            _LOGGER.debug(
                'Failed to retrieve list of services from the network: '
                f'HTTP {resp.status_code}'
            )

    async def bootstrap_join_services(self, service_ids: list[int]) -> None:
        '''
        Joins the services listed in the 'JOIN_SERVICE_IDS'
        environment variable, if we are not already member of them
        '''

        # We first need to get registered services as that will tell
        # us the version of the schema that we should join.

        log_data: dict[str, any] = {'service_ids': service_ids}
        _LOGGER.debug('Got bootstrap joins', extra=log_data)

        account: Account = self.account
        data_store: DataStore = self.data_store

        await self.get_registered_services()
        service_summaries: dict[int, dict[str, str | int | None]] = \
            self.network.service_summaries

        log_data['services_found'] = ','.join(
            [str(service_id) for service_id in service_summaries]
        )
        service_id: int
        for service_id in service_ids or []:
            log_data['service_id'] = service_id
            _LOGGER.debug(
                'Processing bootstrap join for service', extra=log_data
            )

            if service_id in self.account.memberships:
                _LOGGER.debug('We already joined service', extra=log_data)
                continue

            if service_id not in service_summaries:
                _LOGGER.debug(
                    'Can not join service, not found in network',
                    extra=log_data
                )
                continue

            version: int = service_summaries[service_id]['version']
            log_data['version'] = version
            # This joins the service (create secrets, register with the
            # service) but does not persist the membership
            _LOGGER.debug('Auto-joining service', extra=log_data)

            member: Member = await account.join(
                service_id, version, self.local_storage, with_reload=True
            )

            # This updates account.db so the podserver knows it is a member
            await data_store.setup_member_db(
                member_id=member.member_id, service_id=service_id,
                schema=member.schema
            )

            # Make sure we have a restricted token key for this service
            # This first one we create using the account ID. The byohost
            # server will generated the same key and distribute it to the
            # CDN
            _LOGGER.debug(
                f'Auto-generating content key for service {service_id}'
            )
            key_table: Table = data_store.get_table(
                member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
            )

            key_secret: str = sha256(
                (str(account.account_id) + str(service_id)).encode('utf-8')
            ).hexdigest()

            key: ContentKey = await ContentKey.create(
                key=key_secret, table=key_table
            )
            await key.persist()

    async def set_document_store(self, store_type: DocumentStoreType,
                                 cloud_type: CloudType = None,
                                 private_bucket: str = None,
                                 restricted_bucket: str = None,
                                 public_bucket: str = None,
                                 root_dir: str = None) -> None:

        await super().set_document_store(
            store_type, cloud_type, private_bucket, restricted_bucket,
            public_bucket, root_dir
        )

        self.local_storage = await FileStorage.setup(root_dir)

    async def set_data_store(self, store_type: DataStoreType,
                             data_secret: DataSecret) -> DataStore:
        '''
        Sets the storage of membership data
        '''

        self.data_store: DataStore = await DataStore.get_data_store(
            self, store_type, data_secret
        )

        return self.data_store

    async def set_cache_store(self, cache_type: CacheType) -> CacheStore:
        '''
        Sets the cache for membership data for those data classes that have the
        'cache-only' property set.
        '''

        cache_store: CacheStore = await CacheStore.get_cache_store(
            self, cache_type
        )
        self.cache_store = cache_store

        return self.cache_store

    async def review_jwt(self, jwt: JWT) -> None:
        '''
        Reviews the JWT for processing on a pod server

        :param jwt: the received JWT
        :raises: ValueError:
        :returns: (none)
        '''

        if jwt.service_id is None and jwt.issuer_type != IdType.ACCOUNT:
            raise ValueError(
                'Service ID must not specified in the JWT for an account'
            )

        account: Account = config.server.account
        if jwt.issuer_type == IdType.ACCOUNT:
            if jwt.issuer_id != account.account_id:
                raise ValueError(
                    f'Received JWT for wrong account_id: {jwt.issuer_id}'
                )

        elif jwt.issuer_type == IdType.MEMBER:
            account: Account = self.account
            member: Member = await account.get_membership(jwt.service_id)

            if not member:
                # We don't want to give details in the error message as it
                # could allow people to discover which services a pod has
                # joined
                _LOGGER.exception(
                    f'Unknown service ID: {self.service_id}'
                )
                raise ValueError
        else:
            raise ValueError(
                f'Podserver does not support JWTs for {jwt.issuer_type}'
            )

    async def get_jwt_secret(self, jwt: JWT):
        '''
        Load the public key for the secret that was used to sign the jwt.
        '''

        account: Account = self.account

        if jwt.issuer_type == IdType.ACCOUNT:
            secret: AccountSecret = account.tls_secret
        elif jwt.issuer_type == IdType.MEMBER:
            member: Member = await account.get_membership(jwt.service_id)

            if member and member.member_id == jwt.issuer_id:
                secret: MemberSecret = member.data_secret
            else:
                raise ValueError(
                    'JWTs can not be used to query pods other than our own'
                )

        return secret

    def get_app_by_type(self, app_type: AppType, service_id: int
                        ) -> App | None:
        '''
        Returns the app of the given type
        '''

        for app in self.apps.values():
            if app.app_type == app_type and app.service_id == service_id:
                return app

        return None

    async def shutdown(self) -> None:
        '''
        Shuts down the server
        '''

        # Note call_data_api.py tool does not set up the data store
        if self.data_store:
            await self.data_store.close()

        await ApiClient.close_all()

    def accepts_jwts(self) -> bool:
        return True
