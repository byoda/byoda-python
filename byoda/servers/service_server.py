'''
Class ServiceServer derived from Server class for modelling
a server that hosts a BYODA Service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from typing import Self
from typing import TypeVar
from logging import getLogger
from byoda.util.logger import Logger

from byoda.datamodel.service import Service
from byoda.datamodel.network import Network

from byoda.datastore.memberdb import MemberDb
from byoda.datastore.searchdb import SearchDB

from byoda.datacache.asset_cache import AssetCache

from byoda.secrets.member_data_secret import MemberDataSecret

from byoda.storage.filestorage import FileStorage

from byoda.datacache.kv_cache import KVCache

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
    def __init__(self, network: Network, app_config: dict) -> None:
        '''
        Initiates a service server

        :param verify_contract_signatures: should the signature of the service
        schema be verified. Test cases may specify this as 'False'
        '''

        _LOGGER.debug('Initializing service server')
        super().__init__(network)

        self.server_type = ServerType.SERVICE

        self.local_storage = network.paths.storage_driver

        self.service = Service(
            network=self.network,
            service_id=app_config['svcserver']['service_id']
        )

        self.asset_cache: AssetCache | None = None

        self.dns_resolver = DnsResolver(network.name)

        _LOGGER.debug('Initialized service server')

    async def setup(network: Network, app_config: dict) -> Self:
        '''
        Sets up a service server with asychronous member_DB and search DB

        :param network:
        :param app_config: the configuration for the service
        :returns: ServiceServer
        '''

        self = ServiceServer(network, app_config)
        config.server: ServiceServer = self
        service: Service = self.service

        connection_string: str = app_config['svcserver']['member_cache']
        _LOGGER.debug(f'Setting up Redis connections to {connection_string}')
        self.search_db: SearchDB = await SearchDB.setup(
            connection_string, service
        )

        self.member_db: MemberDb = await MemberDb.setup(
            connection_string, service.service_id, network.name
        )

        return self

    async def load_network_secrets(self, storage_driver: FileStorage = None) -> None:
        await self.network.load_network_secrets(storage_driver=storage_driver)

    async def load_secrets(self, password: str) -> None:
        await self.service.load_secrets(
            with_private_key=True,
            password=password
        )

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

        _LOGGER.debug(
            'Loading schema, checking signatures: '
            f'{verify_contract_signatures}'
        )
        service: Service = self.service
        schema_file: str = service.paths.get(Paths.SERVICE_FILE)
        await service.load_schema(
            filepath=schema_file,
            verify_contract_signatures=verify_contract_signatures
        )

        self.member_db.schema = service.schema

    async def setup_asset_cache(self, connection_string: str) -> None:
        '''
        Sets up the asset cache for the service. The asset cache can only
        be created after the schema has been loaded

        :param connection_string: the connection string for the asset cache
        :returns: (none)
        :raises: ValueError
        '''

        if not self.service.schema:
            raise ValueError(
                'schema must be loaded before asset cache can be initialized'
            )

        self.asset_cache: AssetCache = await AssetCache.setup(
            connection_string, self.service,
            asset_class=ASSET_CLASS,
            expiration_window=KVCache.DEFAULT_CACHE_EXPIRATION
        )

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
