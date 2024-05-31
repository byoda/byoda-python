'''
Class ServiceServer derived from Server class for modelling
a server that hosts a BYODA Service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import os
from uuid import UUID
from typing import Literal
from logging import getLogger

from aiosqlite import connect as sqlite_connect

from byoda.datamodel.service import Service
from byoda.datamodel.network import Network
from byoda.datamodel.app import App

from byoda.secrets.member_data_secret import MemberDataSecret

from byoda.storage.filestorage import FileStorage

from byoda.datatypes import ServerType
from byoda.datatypes import IdType
from byoda.datatypes import ClaimStatus
from byoda.datatypes import AppType

from byoda.requestauth.jwt import JWT

from byoda.servers.server import Server

from byoda.util.paths import Paths

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)


class AppServer(Server):
    def __init__(self, app_type: AppType, app_id: UUID | str,
                 network: Network, app_config: dict, routers) -> None:
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

        if app_type == AppType.MODERATE:
            self.fqdn: str = app_config['modserver']['fqdn']

            self.claim_dir: str = app_config['modserver']['claim_dir']
            self.whitelist_dir: str = app_config['modserver']['whitelist_dir']

            os.makedirs(self.whitelist_dir, exist_ok=True)

            for status in ClaimStatus:
                os.makedirs(f'{self.claim_dir}/{status.value}', exist_ok=True)
        elif app_type == AppType.CDN:
            self.keys_dir: str = app_config['cdnserver']['keys_dir']
            self.origins_dir: str = app_config['cdnserver']['origins_dir']
            self.sqlite_db_file: str = app_config['cdnserver'].get('sqlite_db')
            if not self.sqlite_db_file:
                raise ValueError('No sqlite_db defined for CDN app')

        network.paths = self.paths

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

    async def load_network_secrets(self, storage_driver: FileStorage = None
                                   ) -> None:
        await self.network.load_network_secrets(storage_driver=storage_driver)

    async def load_secrets(self, password: str) -> None:
        await self.app.load_secrets(with_private_key=True, password=password)

    async def load_schema(self, verify_contract_signatures: bool = True
                          ) -> None:
        paths: Paths = self.service.paths
        schema_file: str = paths.get(Paths.SERVICE_FILE)
        await self.service.load_schema(
            filepath=schema_file,
            verify_contract_signatures=verify_contract_signatures
        )

        self.member_db.schema = self.service.schema

    async def review_jwt(self, jwt: JWT) -> None:
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

    async def get_jwt_secret(self, jwt: JWT) -> MemberDataSecret:
        '''
        Load the secret used to sign the jwt.
        '''
        secret: MemberDataSecret = MemberDataSecret(
            jwt.issuer_id, jwt.service_id, None
        )

        try:
            await secret.load(with_private_key=False)
        except FileNotFoundError:
            secret = await secret.download(
                jwt.issuer_id, self.service.service_id,
                self.service.network.name
            )

        return secret

    def accepts_jwts(self) -> Literal[True]:
        return True

    async def create_membership_table(self) -> None:
        '''
        Create the Sqlite table to store mappings from member_id to
        bucket/container name so the CDN can proxy requests to the
        correct storage bucket
        '''

        async with sqlite_connect(self.sqlite_db_file) as conn:
            await conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS memberships (
                    member_id TEXT NOT NULL,
                    service_id INTEGER NOT NULL,
                    visibility TEXT NOT NULL,
                    container TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    PRIMARY KEY(member_id, service_id, visibility)
                )
                '''
            )
            await conn.commit()
