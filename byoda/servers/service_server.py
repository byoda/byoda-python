'''
Class ServiceServer derived from Server class for modelling
a server that hosts a BYODA Service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import TypeVar

from byoda.datamodel.service import Service
from byoda.datamodel.network import Network

from byoda.datastore.memberdb import MemberDb

from byoda.datatypes import ServerType

from byoda.servers.server import Server

from byoda.util.dnsresolver import DnsResolver

from byoda.util.paths import Paths

_LOGGER = logging.getLogger(__name__)

RegistrationStatus = TypeVar('RegistrationStatus')


class ServiceServer(Server):
    def __init__(self, app_config: dict):
        '''
        Initiates a service server

        :param verify_contract_signatures: should the signature of the service
        schema be verified. Test cases may specify this as 'False'
        '''
        network = Network(
            app_config['svcserver'], app_config['application']
        )
        super().__init__(network)

        self.server_type = ServerType.SERVICE

        self.service = Service(
            self.network, None, app_config['svcserver']['service_id']
        )

        self.member_db: MemberDb = MemberDb(app_config['svcserver']['cache'])
        self.member_db.service_id = self.service.service_id

        self.dns_resolver = DnsResolver(network.name)

    def load_secrets(self, password: str):
        self.service.load_secrets(
            with_private_key=True,
            password=password
        )

        self.service.tls_secret.save_tmp_private_key()

    def load_schema(self, verify_contract_signatures: bool = True):
        schema_file = self.service.paths.get(Paths.SERVICE_FILE)
        self.service.load_schema(
            filepath=schema_file,
            verify_contract_signatures=verify_contract_signatures
        )

        self.member_db.schema = self.service.schema
