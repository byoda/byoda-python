'''
Class ServiceServer derived from Server class for modelling
a server that hosts a BYODA Service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging
from typing import TypeVar

from byoda.datamodel.service import Service
from byoda.datamodel.network import Network

from byoda.datastore.memberdb import MemberDb
from byoda.datastore.searchdb import SearchDB

from byoda.secrets.member_secret import MemberSecret

from byoda.datatypes import ServerType
from byoda.datatypes import IdType

from byoda.servers.server import Server

from byoda.util.dnsresolver import DnsResolver

from byoda.util.paths import Paths

from byoda import config

_LOGGER = logging.getLogger(__name__)

RegistrationStatus = TypeVar('RegistrationStatus')

JWT = TypeVar('JWT')


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

        self.member_db: MemberDb = MemberDb(app_config['svcserver']['cache'])
        self.search_db: SearchDB = SearchDB(
            app_config['svcserver']['cache'], self.service
        )
        self.member_db.service_id = self.service.service_id

        self.dns_resolver = DnsResolver(network.name)

    async def load_network_secrets(self):
        await self.network.load_network_secrets()

    async def load_secrets(self, password: str):
        await self.service.load_secrets(
            with_private_key=True,
            password=password
        )

        self.service.tls_secret.save_tmp_private_key()

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
        Load the secret used to sign the jwt. As a service is the CA for
        member secrets, the service server should have access to the public
        key of all member secrets
        '''
        secret: MemberSecret = MemberSecret(
            jwt.issuer_id, jwt.service_id, None,
            config.server.service.network
        )

        await secret.load(with_private_key=False)

        return secret

    def accepts_jwts(self):
        return True
