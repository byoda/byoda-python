'''
Class for modeling the different server types, ie.:
POD server, directory server, service server

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import logging
from enum import Enum
from typing import TypeVar


from byoda.util import Paths

from byoda import config

from byoda.datatypes import CloudType

from byoda.datastore import DocumentStoreType, DocumentStore
from byoda.util.api_client.restapi_client import RestApiClient

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network')
RegistrationStatus = TypeVar('RegistrationStatus')


class ServerType(Enum):
    Pod         = 'pod'             # noqa: E221
    Directory   = 'directory'       # noqa: E221
    Service     = 'service'         # noqa: E221


class Server:
    def __init__(self):
        self.server_type = None
        self.network = None
        self.account = None
        self.service = None
        self.document_store = None
        self.cloud = None
        self.paths = None

    def load_secrets(self, password: str = None):
        '''
        Loads the secrets of the server
        '''
        raise NotImplementedError

    def set_document_store(self, store_type: DocumentStoreType,
                           cloud_type: CloudType = None,
                           bucket_prefix: str = None, root_dir: str = None
                           ) -> None:

        self.cloud = cloud_type

        self.document_store = DocumentStore.get_document_store(
            store_type, cloud_type=cloud_type, bucket_prefix=bucket_prefix,
            root_dir=root_dir
        )


class PodServer(Server):
    def __init__(self):
        super().__init__()

        self.server_type = ServerType.Pod
        self.service_summaries = None

    def load_secrets(self, password: str = None):
        '''
        Loads the secrets used by the podserver
        '''
        self.account.load_secrets()

        # We use the account secret as client TLS cert for outbound
        # requests and as private key for the TLS server
        filepath = self.account.tls_secret.save_tmp_private_key()

        config.requests.cert = (
            self.account.tls_secret.cert_file, filepath
        )

    def get_registered_services(self, network):
        '''
        Downloads a list of service summaries
        '''

        self.network = network

        url = network.paths.get(Paths.NETWORKSERVICES_API)
        response = RestApiClient.call(url)

        if response.status_code == 200:
            self.service_summaries = response.json()
            _LOGGER.debug(
                f'Read summaries for {len(self.service_summaries)} services'
            )
        else:
            _LOGGER.debug(
                'Failed to retrieve list of services from the network: '
                f'HTTP {response.status_code}'
            )

    def load_joined_services(self, network):
        '''
        Load the services that the account for the pod has joined
        '''

        self.network = network

        folders = network.paths.storage_driver.get_folders(
            Paths.SERVICES_DIR
        )
        for folder in [f for f in folders if f.startswith('service-')]:
            service_id = folder.split('-')[-1]

            service = network.add_service(
                service_id, RegistrationStatus.SchemaSigned
            )

            service_file = self.network.paths.get(
                Paths.SERVICE_FILE, service_id=service_id
            )

            try:
                service.load_schema(service_file)
            except (ValueError, RuntimeError, OSError) as exc:
                _LOGGER.exception(
                    f'Failed to load service from {service_file}: {exc}'
                )


class DirectoryServer(Server):
    def __init__(self):
        super().__init__()

        self.server_type = ServerType.Directory

    def load_secrets(self, connection: str = None):
        '''
        Loads the secrets used by the directory server
        '''
        self.network.load_secrets()

    def get_registered_services(self, network: Network):
        '''
        Get the list of registered services in the network by
        scanning the directory tree. Add the services to the
        network.services dict if they are not already in there.
        '''

        self.network = network

        service_dir = network.paths.get(Paths.SERVICES_DIR)

        services_dirs = [
            svcdir for svcdir in next(os.walk(service_dir))[1]
            if svcdir.startswith('service-')
        ]

        for svcdir in services_dirs:
            service_id = svcdir.split('-')[-1]
            if network.services.get(service_id):
                # We already have the service in memory
                continue

            service = network.add_service(service_id)

            service_file = self.network.paths.get(
                Paths.SERVICE_FILE, service_id=service_id
            )
            if os.path.exists(service_file):
                service.load_schema(service_file)
            else:
                service.registration_status = service.get_registration_status()


class ServiceServer(Server):
    def __init__(self):
        super().__init__()

        self.server_type = ServerType.Service

    def load_secrets(self, password: str = None):
        '''
        Loads the secrets used by the directory server
        '''

        self.service.load_secrets(with_private_key=True, password=password)
