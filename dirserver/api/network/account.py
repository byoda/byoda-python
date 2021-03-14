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
from byoda.requestauth import AccountRequestAuth

from byoda.datatypes import IdType

from byoda.datamodel import Network

from byoda.datastore import CertStore

from byoda.schema import Stats, StatsResponseSchema
from byoda.schema import Cert, CertResponseSchema
from byoda.schema import CertSigningRequestSchema

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

        auth = AccountRequestAuth(required=False)

        network = config.network

        response = self._get(auth, network)

        return response

    def _get(self, auth: AccountRequestAuth, network: Network) -> Stats:
        '''
        Get some account stats for the network and a suggested UUID

        :param auth: instance of byoda.requestauth.AccountRequestAuth
        :param network: instance of byoda.datamodel.network
        :returns:
        :raises: (none)
        '''

        try:
            stats = None
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span('account_get'):
                dns_update = 0
                if auth.is_authenticated:
                    dns_update = network.dnsdb.create_update(
                        auth.account_id, IdType.ACCOUNT, auth.remote_addr
                    )
                stats = Stats(
                    accounts=1, services=2, uuid=uuid4(),
                    remote_addr=auth.remote_addr, dns_update=dns_update > 0
                )
        except Exception as exc:
            _LOGGER.warning('Failed to instantiate Stats: %s', exc)

        return stats

    @flask_log_fields
    @api.doc(
        'Processes a Certificate Signing Request and returns the signed cert'
    )
    @accepts(schema=CertSigningRequestSchema, api=api)
    @responds(schema=CertResponseSchema)
    def post(self):
        '''
        '''

        _LOGGER.debug('POST Account API called')

        auth = AccountRequestAuth(required=False)

        network = config.network

        data = request.parsed_obj
        csr = data.csr

        response = self._post(auth, network, csr)

        return response

    def _post(self, auth, network, csr):
        '''
        Get some account stats for the network and a suggested UUID

        :param network: instance of byoda.datamodel.network
        :returns: uuid, http_status
        :raises: (none)
        '''

        certstore = CertStore(network.accounts_ca)

        certchain = None
        try:
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span('account_get'):
                certchain_str = certstore.sign(
                    csr, IdType.ACCOUNT, auth.remote_addr
                )
                certchain = Cert(certificate=certchain_str)
        except ValueError as exc:
            _LOGGER.info(f'Invalid CSR: {exc}')
        except Exception as exc:
            _LOGGER.warning(f'Failed to proces the CSR: {exc}')

        if certchain:
            return certchain
