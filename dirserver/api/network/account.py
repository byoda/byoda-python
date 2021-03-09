'''
/network/account api API

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''


import logging
from uuid import uuid4

from flask import request
from flask_restx import Namespace, Resource, fields

from flask_accepts import accepts, responds

from opentelemetry import trace

from byoda.util.logger import flask_log_fields

from byoda.datastore import CertStore

from byoda.schema import Stats, StatsResponseSchema
from byoda.schema import Cert, CertResponseSchema
from byoda.schema import CertSigningRequest, CertSigningRequestSchema

import byoda.config as config


_LOGGER = logging.getLogger(__name__)


api = Namespace(
    'v1/network/account',
    description='CRUD for accounts on directory server'
)

model = api.model('status', {'message': fields.String})


@api.route('/')
@api.doc('Get the status of the application server')
class AccountApi(Resource):
    @flask_log_fields
    @api.doc('Get stats on the accounts in the network and a UUID suggestion')
    @responds(schema=StatsResponseSchema)
    def get(self):
        '''
        '''

        _LOGGER.debug('GET Account API called')

        network = config.network

        response = self._get(network)

        return response

    def _get(self, network):
        '''
        Get some account stats for the network and a suggested UUID

        :param network: instance of byoda.datamodel.network
        :returns: uuid, http_status
        :raises: (none)
        '''

        try:
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span('account_get'):
                stats = Stats(
                    accounts=1, services=2, uuid=uuid4(),
                    ipaddress=request.remote_addr
                )
        except Exception as exc:
            _LOGGER.debug('Failed to instantiate Stats: %s', exc)

        return stats

    @flask_log_fields
    @api.doc(
        'Processes a Certificate Signing Request and returns the signed cert'
    )
    # @accepts(dict(name='csr', type=str))
    @accepts(
         dict(name='blah', type=str), schema=CertSigningRequestSchema, api=api
    )
    @responds(schema=CertResponseSchema)
    def post(self):
        '''
        '''

        _LOGGER.debug('POST Account API called')

        network = config.network

        data = request.parsed_obj
        csr = data.csr
        client_ip = request.remote_addr
        x_forwarded_for = request.get('X-Forwarded-For')
        if x_forwarded_for:
            client_ip = x_forwarded_for.split(' ')[-1]

        response = self._post(network, csr, client_ip)

        return response

    def _post(self, network, csr, client_ip):
        '''
        Get some account stats for the network and a suggested UUID

        :param network: instance of byoda.datamodel.network
        :returns: uuid, http_status
        :raises: (none)
        '''

        certstore = CertStore(network.account_ca)

        cert = None
        try:
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span('account_get'):
                cert = certstore.sign(csr, client_ip)
        except ValueError as exc:
            _LOGGER.info(f'Invalid CSR: {exc}')
        except Exception as exc:
            _LOGGER.warning(f'Failed to proces the CSR: {exc}')

        return cert
