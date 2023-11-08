'''
Class ServiceServer derived from Server class for modelling
a server that hosts a BYODA Service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from typing import TypeVar
from logging import getLogger
from byoda.util.logger import Logger

from byoda.datamodel.service import Service
from byoda.datamodel.network import Network

from byoda.datastore.memberdb import MemberDb
from byoda.datastore.searchdb import SearchDB

from byoda.datacache.assetcache import AssetCache

from byoda.secrets.member_data_secret import MemberDataSecret

from byoda.storage.filestorage import FileStorage

from byoda.datacache.kv_cache import DEFAULT_CACHE_EXPIRATION

from byoda.datatypes import ServerType
from byoda.datatypes import IdType

from byoda.servers.server import Server

from byoda.util.dnsresolver import DnsResolver

from byoda.util.paths import Paths

from byoda import config

_LOGGER: Logger = getLogger(__name__)

RegistrationStatus = TypeVar('RegistrationStatus')

JWT = TypeVar('JWT')

ASSET_CLASS: str = 'public_assets'


class ServiceServer(Server):
    def __init__(self, network: Network, app_config: dict):
        '''
        Initiates a service server

        :param verify_contract_signatures: should the signature of the service
        schema be verified. Test cases may specify this as 'False'
        '''

        super().__init__(network)

        self.server_type = ServerType.SERVICE

        self.local_storage = network.paths.storage_driver

        self.service = Service(
            network=self.network,
            service_id=app_config['svcserver']['service_id']
        )

        self.kvcache = None
        self.dns_resolver = DnsResolver(network.name)

    async def setup(network: Network, app_config: dict):
        '''
        Sets up a service server with asychronous member_DB and search DB

        :param network:
        :param app_config: the configuration for the service
        :returns: ServiceServer
        '''

        self = ServiceServer(network, app_config)

        self.search_db: SearchDB = await SearchDB.setup(
            app_config['svcserver']['cache'], self.service
        )

        self.asset_cache: AssetCache = await AssetCache.setup(
            app_config['svcserver']['cache'],
            self.service,
            asset_class=ASSET_CLASS,
            expiration_window=DEFAULT_CACHE_EXPIRATION
        )

        self.member_db: MemberDb = await MemberDb.setup(
            app_config['svcserver']['cache']
        )
        self.member_db.service_id = self.service.service_id

        return self

    async def load_network_secrets(self, storage_driver: FileStorage = None):
        await self.network.load_network_secrets(storage_driver=storage_driver)

    async def load_secrets(self, password: str):
        await self.service.load_secrets(
            with_private_key=True,
            password=password
        )

        self.asset_cache.tls_secret = self.service.tls_secret

        self.service.tls_secret.save_tmp_private_key()

    async def load_schema(self, verify_contract_signatures: bool = True
                          ) -> None:
        '''
        Loads the schema for the service

        :param verify_contract_signatures: should the signatures of the service
        be verified.
        :returns: (none)
        :raises: (none)
        '''

        service: Service = self.service
        schema_file: str = service.paths.get(Paths.SERVICE_FILE)
        await service.load_schema(
            filepath=schema_file,
            verify_contract_signatures=verify_contract_signatures
        )

        self.member_db.schema = service.schema

    async def review_jwt(self, jwt: JWT):
        '''
        Reviews the JWT for processing on a service server

        :param jwt: the received JWT
        :raises: ValueError:
        :returns: (none)
        '''

        if jwt.service_id is None:
            raise ValueError('No service ID specified in the JWT')

        if jwt.issuer_type != IdType.MEMBER:
            raise ValueError(
                'Service API can only be called with a JWT for a member'
            )

    async def get_jwt_secret(self, jwt: JWT):
        '''
        Load the secret used to sign the jwt. As a service is the CA for
        member secrets, the service server should have access to the public
        key of all member secrets
        '''
        secret: MemberDataSecret = MemberDataSecret(
            jwt.issuer_id, jwt.service_id, None,
            config.server.service.network
        )

        await secret.load(with_private_key=False)

        return secret

    def accepts_jwts(self):
        return True
