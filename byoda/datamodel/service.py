'''
Class for modeling a service on a social network

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

from __future__ import annotations

import json
import logging

_LOGGER = logging.getLogger(__name__)

DEFAULT_NETWORK = 'byoda.net'


class Service:
    '''
    Models a service on a BYODA network.
    This class is used both by the SDK for hosting a service
    and by pods
    '''

    def __init__(self, name: str = None, service_id: int = None,
                 network: str = DEFAULT_NETWORK):
        self.name = name
        self.service_id = service_id
        self.network = network
        self.schema = None
        self.public_key = None

    @classmethod
    def get_service(cls, network: str = DEFAULT_NETWORK, filename: str = None
                    ) -> Service:
        '''
        Factory for Service class.
        TODO: add typing for return value after switch to python3.9
        '''

        service = Service(network=network)

        service.load(filename=filename)

        return service

    def load(self, filename: str = None):
        '''
        '''

        # TODO: implement validation of the service definition using
        # JSON-Schema

        if filename is None:
            raise NotImplementedError(
                'Downloading service definitions from the directory server '
                'of a network is not yet implemented'
            )

        with open(filename) as file_desc:
            data = json.load(file_desc)

        self.service_id = self.schema['service_id']
        self.name = self.schema['name']
        self.schema = data['schema']

        # TODO: check signature of service data contract
        if self.schema.get('contract_signature'):
            raise NotImplementedError(
                'Data contract signature verification is not yet implemented'
            )
        self.contract_signature = None

        _LOGGER.debug(
            f'Read service {self.name} without signature verification'
        )
