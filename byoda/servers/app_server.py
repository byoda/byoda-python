'''
Class ServiceServer derived from Server class for modelling
a server that hosts a BYODA Service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from uuid import UUID

from byoda.datamodel.service import Service
from byoda.datamodel.network import Network
from byoda.datamodel.app import App

from byoda.secrets.member_secret import MemberSecret

from byoda.storage.filestorage import FileStorage

from byoda.datatypes import ServerType
from byoda.datatypes import IdType
from byoda.datatypes import ClaimStatus

from byoda.requestauth.jwt import JWT

from byoda.servers.server import Server

from byoda.util.paths import Paths

_LOGGER = logging.getLogger(__name__)


class AppServer(Server):
    def __init__(self, app_id: UUID | str, network: Network, app_config: dict):
        '''
        Initiates a service server
        '''

        super().__init__(network)

        self.server_type = ServerType.APP
        if isinstance(app_id, str):
            self.app_id = UUID(app_id)
        else:
            self.app_id: UUID = app_id

        self.paths = Paths(
            network=network.name,
            root_directory=app_config['appserver']['root_dir']
        )

        self.local_storage: FileStorage = self.paths.storage_driver

        self.fqdn = app_config['appserver']['fqdn']

        self.claim_dir: str = app_config['appserver']['claim_dir']
        self.whitelist_dir: str = app_config['appserver']['whitelist_dir']

        network.paths: Paths = self.paths

        self.service = Service(
            network=self.network,
            service_id=app_config['appserver']['service_id']
        )

        self.app: App = App(self.app_id, self.service)

    def get_claim_filepath(self, status: ClaimStatus,
                           id: UUID | str = None) -> str:
        '''
        Returns the file-path for a claim with a given status and id

        :params status: status of the claim
        :params id: id of the claim, either asset_id or member_id. If not
        provided, the filepath for the status directory is returned with a
        trailing '/'
        :returns: filepath
        :raises:
        '''

        filepath: str = f'{self.claim_dir}/{status.value}/'
        if id:
            filepath = f'{filepath}{id}.json'

        return filepath

    async def load_network_secrets(self, storage_driver: FileStorage = None):
        await self.network.load_network_secrets(storage_driver=storage_driver)

    async def load_secrets(self, password: str):
        await self.app.load_secrets(with_private_key=True, password=password)

    async def load_schema(self, verify_contract_signatures: bool = True):
        schema_file = self.service.paths.get(Paths.SERVICE_FILE)
        await self.service.load_schema(
            filepath=schema_file,
            verify_contract_signatures=verify_contract_signatures
        )

        self.member_db.schema = self.service.schema

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
        Load the secret used to sign the jwt.
        '''
        secret: MemberSecret = MemberSecret(
            jwt.issuer_id, jwt.service_id, None, paths=self.paths,
            network_name=self.network.name
        )

        try:
            await secret.load(with_private_key=False)
        except FileNotFoundError:
            local_root_ca_cert_filepath = (
                self.paths.storage_driver.local_path.lstrip('/') +
                self.paths.get(Paths.NETWORK_ROOT_CA_CERT_FILE)
            )
            secret = await MemberSecret.download(
                jwt.issuer_id, self.service.service_id,
                self.service.network.name, self.paths,
                root_ca_cert_file=local_root_ca_cert_filepath
            )

        return secret

    def accepts_jwts(self):
        return True
