'''
Class DirectoryServer derived from Server class for modelling
a server that hosts a BYODA Network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import logging
from typing import TypeVar

from byoda.datastore.dnsdb import DnsDb

from byoda.datatypes import ServerType

from byoda.util.paths import Paths

from .server import Server

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network')
RegistrationStatus = TypeVar('RegistrationStatus')


class DirectoryServer(Server):
    def __init__(self, network: Network):
        super().__init__(network)

        self.server_type = ServerType.DIRECTORY

    async def connect_db(self, dnsdb_connection_string: str):
        self.network.dnsdb = await DnsDb.setup(
            dnsdb_connection_string, self.network.name
        )

    def load_secrets(self, connection: str = None):
        '''
        Loads the secrets used by the directory server
        '''

        self.network.load_secrets()

    async def get_registered_services(self):
        '''
        Get the list of registered services in the network by
        scanning the directory tree. Add the services to the
        network.services dict if they are not already in there.
        '''

        network = self.network

        service_dir = network.paths.get(
            network.paths.root_directory + '/' + Paths.SERVICES_DIR
        )

        services_dirs = [
            svcdir for svcdir in os.listdir(service_dir)
            if svcdir.startswith('service-')
        ]

        _LOGGER.debug(
            f'Found services {", ".join(services_dirs)} in {service_dir}'
        )

        for svcdir in services_dirs:
            service_id = int(svcdir.split('-')[-1])
            if network.services.get(service_id):
                # We already have the service in memory
                _LOGGER.debug(f'Skipping loading of service {service_id}')
                continue

            service = await network.add_service(service_id)

            service_file = service.paths.get(Paths.SERVICE_FILE)
            if await service.paths.exists(service_file):
                await service.load_schema(service_file)
            else:
                service.registration_status = \
                    await service.get_registration_status()

            _LOGGER.debug(f'Loaded service {service_id}')
