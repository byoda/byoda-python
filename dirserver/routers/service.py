'''
/network/service API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''


import logging

from fastapi import APIRouter, Depends, Request

from byoda.datatypes import IdType

from byoda.datastore import CertStore

from byoda.models import ServiceSummariesResponseModel

from byoda.models import CertSigningRequestModel
from byoda.models import SignedCertResponseModel

from byoda.models import SchemaModel, SchemaResponseModel

from byoda import config

from ..dependencies.servicerequest_auth import ServiceRequestAuthFast

_LOGGER = logging.getLogger(__name__)

router = APIRouter(
    prefix='/api/v1/network',
    dependencies=[]
)


@router.get('/service', response_model=ServiceSummariesResponseModel)
def get_service(request: Request, skip: int = 0, count: int = 0):
    '''
    Get a list of summaries of available services.
    This API is called by pods
    This API does not require authentication; service schemas are
    public information
    '''

    _LOGGER.debug(f'GET Service API called from {request.client.host}')

    network = config.server.network

    services = list(network.services.values())

    if count == 0:
        count = len(services)

    result = {
        'service_summaries': [
            {
                'service_id': service.service_id,
                'version': service.schema.json_schema['version'],
                'name': service.schema.json_schema['name'],
                'title': service.schema.json_schema.get('title'),
                'description': service.schema.json_schema.get('description'),
                'supportemail': service.schema.json_schema.get('supportemail'),
            } for service in services[skip: count]
        ]
    }
    return result


@router.post('/service', response_model=SignedCertResponseModel)
def post_service(request: Request, csr: CertSigningRequestModel):
    '''
    Submit a Certificate Signing Request for the ServiceCA certificate
    and get the cert signed by the network services CA
    This API is called by services
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy
    '''

    _LOGGER.debug(f'POST Service API called from {request.client.host}')

    network = config.server.network

    certstore = CertStore(network.services_ca)

    # TODO: SECURITY: check if the CSR is for a service_id that already
    # exists and that we haven't already signed a CSR for
    # this service_id recently
    certchain = certstore.sign(
        csr.csr, IdType.SERVICE_CA, request.client.host
    )

    signed_cert = certchain.cert_as_string()
    cert_chain = certchain.cert_chain_as_string()

    root_ca_cert = network.root_ca.cert_as_pem()
    data_cert = network.data_secret.cert_as_pem()

    return {
        'signed_cert': signed_cert,
        'cert_chain': cert_chain,
        'network_root_ca_cert': root_ca_cert,
        'data_cert': data_cert,
    }


@router.patch('/service', response_model=SchemaResponseModel)
def patch_service(request: Request, schema: SchemaModel,
                  auth: ServiceRequestAuthFast = Depends(
                     ServiceRequestAuthFast)):
    '''
    Submit a new (revision of a) service schema, aka data contract
    for signing with the Network Data secret
    This API is called by services

    '''

    _LOGGER.debug(f'POST Service API called from {request.client.host}')

    network = config.server.network

    # TODO: create a whole bunch of schema validation tests
    # including one to just deserialize and reserialize and
    # verify the signatures again

    return {
        'status': 'ACCEPTED',
        'errors': [],
        'timestamp': 'now',
    }
