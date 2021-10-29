'''
/network/service API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3

The registration of a service in the network takes four steps:
1: Create a Service CA key/cert and request signature by the Network Services
   CA via a POST /api/v1/network/service request.
2: Register the service and its data cert using a
   PUT /api/v1/network/service/{service_id} request.
3: Submit the service-signed schema for the service and get it signed by
   the network using the PATCH /api/v1/network/service request.
4: Download the fully signed schema and publish it on the web site for the
   service using the GET /api/v1/network/service request.
'''

import os
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import HTTPException

from byoda.datamodel.service import RegistrationStatus

from byoda.datatypes import IdType, ReviewStatusType

from byoda.datamodel import Service
from byoda.datamodel import Schema
from byoda.datastore import CertStore
from byoda.servers import Server
from byoda.datamodel import Network

from byoda.models import ServiceSummariesModel
from byoda.models import CertChainRequestModel
from byoda.models import CertSigningRequestModel
from byoda.models import SignedServiceCertResponseModel
from byoda.models import SchemaModel, SchemaResponseModel
from byoda.models.ipaddress import IpAddressResponseModel

from byoda.secrets import Secret
from byoda.secrets import ServiceCaSecret
from byoda.secrets import ServiceDataSecret

from byoda.util import Paths
from byoda.util import SignatureType

from byoda import config

from ..dependencies.servicerequest_auth import ServiceRequestAuthFast

_LOGGER = logging.getLogger(__name__)

MAX_SERVICE_LIST = 100

router = APIRouter(
    prefix='/api/v1/network',
    dependencies=[]
)


@router.get('/services', response_model=ServiceSummariesModel)
def get_services(request: Request, skip: int = 0, count: int = 0):
    '''
    Get a list of summaries of the available services. This API is called by
    pods. This API does not require authentication as service schemas are
    public information
    '''

    _LOGGER.debug(f'GET Services API called from {request.client.host}')

    server: Server = config.server
    network: Network = config.server.network

    server.get_registered_services(network)

    services = list(network.services.values())

    if count == 0:
        count = max(len(services), MAX_SERVICE_LIST)

    result = {
        'service_summaries': [
            {
                'service_id': service.service_id,
                'version': service.schema.version,
                'name': service.schema.name,
                'description': service.schema.description,
                'owner': service.schema.owner,
                'website': service.schema.website,
                'supportemail': service.schema.supportemail,
            } for service in services[skip: count]
            if service.schema and service.schema.version
        ]
    }
    return result


@router.get('/service/{service_id}', response_model=SchemaModel)
def get_service(request: Request, service_id: int):
    '''
    Get either the data contract of the specified service or a list of
    summaries of the available services. This API is called by pods
    This API does not require authentication as service schemas are
    public information
    '''

    _LOGGER.debug(f'GET Service API called from {request.client.host}')

    network = config.server.network

    if service_id not in network.services:
        # So this worker process does not know about the service. Let's
        # see if a CSR for the service secret has previously been signed
        # and the resulting cert saved
        if not Service.is_registered(service_id):
            raise ValueError(f'Request for unknown service: {service_id}')

        service = network.add_service(service_id)
    else:
        service = network.services.get(service_id)
        if service is None:
            raise ValueError(f'Unkown service id: {service_id}')

        if not service.schema:
            service.registration_status = service.get_registration_status()
            if service.registration_status == RegistrationStatus.SchemaSigned:
                filepath = network.paths.get(
                    Paths.SERVICE_FILE, service_id=service_id
                )
                service.load_schema(filepath)

    if not service.schema:
        raise HTTPException(404, f'Service {service_id} not found')

    return service.schema.json_schema


@router.post(
    '/service', response_model=SignedServiceCertResponseModel, status_code=201
)
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

    # The Network Services CA signs the CSRs for Service CAs
    certstore = CertStore(network.services_ca)

    # We sign the cert first, then extract the service ID from the
    # signed cert and check if the service with the service ID already
    # exists.
    # TODO: extract common name from the CSR so that this code will
    # have a more logical flow where we check first before we sign
    certchain = certstore.sign(
        csr.csr, IdType.SERVICE_CA, request.client.host
    )

    # We make sure the key for the services in the network exists, even if
    # the schema for the service has not yet been provided through the PATCH
    # API
    commonname = Secret.extract_commonname(certchain.signed_cert)
    entity_id = Secret.review_commonname_by_parameters(
        commonname, network.name, uuid_identifier=False,
        check_service_id=False
    )

    service_id = entity_id.service_id
    if service_id is None:
        raise ValueError(
            f'No service id found in common name {commonname}'
        )

    if service_id in network.services:
        raise ValueError(
            f'A CA certificate for service ID {service_id} has already '
            'been signed'
        )

    # Create the service and add it to the network
    service = Service(network=network, service_id=service_id)
    network.services[entity_id.service_id] = service

    # Get the certs as strings so we can return them
    signed_cert = certchain.cert_as_string()
    cert_chain = certchain.cert_chain_as_string()

    # We save the public key in the network directory tree. Not sure
    # if we actually need to do this as we can check any cert of the service
    # and its members through the cert chain that is chained to the network
    # root CA
    service.service_ca = ServiceCaSecret(None, service.service_id, network)
    service.service_ca.cert = certchain.signed_cert
    service.service_ca.cert_chain = certchain.cert_chain

    os.makedirs(os.path.dirname(service.service_ca.cert_file), exist_ok=True)

    # If someone else already registered a Service then saving the cert will
    # raise an exception
    try:
        service.service_ca.save(overwrite=False)
    except PermissionError:
        raise HTTPException(409, 'Service CA certificate already exists')

    data_cert = network.data_secret.cert_as_pem()

    return {
        'signed_cert': signed_cert,
        'cert_chain': cert_chain,
        'network_data_cert_chain': data_cert,
    }


@router.put('/service/{service_id}', response_model=IpAddressResponseModel)
def put_service(request: Request, service_id: int,
                certchain: CertChainRequestModel,
                auth: ServiceRequestAuthFast = Depends(
                    ServiceRequestAuthFast)):
    '''
    Registers a known service with its IP address and its data cert
    '''

    _LOGGER.debug(f'PUT Service API called from {request.client.host}')

    network = config.server.network

    if service_id != auth.service_id:
        raise ValueError(
            f'Service ID {service_id} of PUT call does not match '
            f'service ID {auth.service_id} in client cert'
        )

    if service_id not in network.services:
        # So this worker process does not know about the service. Let's
        # see if a CSR for the service secret has previously been signed
        # and the resulting cert saved
        if not Service.is_registered(service_id):
            raise ValueError(f'Registration for unknown service: {service_id}')

        service = Service(network, service_id=service_id)
        service.registration_status = RegistrationStatus.CsrSigned
        network.services[service_id] = service
    else:
        service = network.services.get(service_id)
        if service is None:
            raise ValueError(f'Unkown service id: {service_id}')

    if not service.data_secret:
        service.data_secret = ServiceDataSecret(
            service.name, service_id, network
        )

    service.data_secret.from_string(certchain.certchain)

    service.data_secret.save(overwrite=True)

    _LOGGER.debug(
        f'Updating registration for service id {service_id} with remote'
        f'address {auth.remote_addr}'
    )

    network.dnsdb.create_update(
        None, IdType.SERVICE, auth.remote_addr, service_id=service_id
    )

    return {
        'ipv4_address': auth.remote_addr
    }


@router.patch('/service/{service_id}', response_model=SchemaResponseModel)
def patch_service(request: Request, schema: SchemaModel, service_id: int,
                  auth: ServiceRequestAuthFast = Depends(
                     ServiceRequestAuthFast)):
    '''
    Submit a new (revision of a) service schema, aka data contract
    for signing with the Network Data secret
    This API is called by services

    '''

    _LOGGER.debug(f'POST Service API called from {request.client.host}')

    if service_id != auth.service_id:
        raise HTTPException(
            403, 'Service ID query parameter does not match the client cert'
        )

    if service_id != schema.service_id:
        raise HTTPException(
            403, f'Service_ID query parameter {service_id} does not match '
            f'the ServiceID parameter in the schema {schema.service_id}'
        )
    network = config.server.network

    # TODO: create a whole bunch of schema validation tests
    # including one to just deserialize and reserialize and
    # verify the signatures again

    status = ReviewStatusType.ACCEPTED
    errors = []

    if not schema.signatures:
        status = ReviewStatusType.REJECTED
        errors.append('Missing service signature')
    else:
        if (not schema.signatures['service']
                or not schema.signatures['service'].get('signature')):
            status = ReviewStatusType.REJECTED
            errors.append('Missing service signature')

    if schema.signatures.get('network'):
        status = ReviewStatusType.REJECTED
        errors.append('network signature already present')

    service_id = schema.service_id
    if service_id != auth.service_id:
        status = ReviewStatusType.REJECTED
        errors.append(
            f'Service ID {service_id} in schema does not match service '
            f'id {auth.service_id} in client cert'
        )
    else:
        if service_id not in network.services:
            # So this worker process does not know about the service. Let's
            # see if a CSR for the service secret has previously been signed
            # and the resulting cert saved
            if not Service.is_registered(service_id):
                service = None
            else:
                service = Service(network, service_id=service_id)
                service.registration_status = RegistrationStatus.CsrSigned
                # Add service to in-memory cache
                network.services[service_id] = service
        else:
            service = network.services.get(service_id)

        if not service:
            status = ReviewStatusType.REJECTED
            errors.append(f'Unregistered service ID {service_id}')
        else:
            if service.schema and schema.version <= service.schema['version']:
                status = ReviewStatusType.REJECTED
                errors.append(
                    f'Schema version {schema.version} is less than current '
                    f'schema version '
                )
            else:
                service_contract = Schema(schema.as_dict())
                try:
                    if not service.data_secret:
                        service.data_secret = ServiceDataSecret(
                            None, service_id, network
                        )
                        service.data_secret.load(with_private_key=False)
                    service_contract.verify_signature(
                        service.data_secret, SignatureType.SERVICE
                    )
                    service.schema = service_contract
                    service.schema.create_signature(
                        network.data_secret, SignatureType.NETWORK
                    )
                    storage_driver = network.paths.storage_driver
                    filepath = network.paths.get(Paths.SERVICE_FILE)
                    service_contract.save(filepath, storage_driver)
                except ValueError:
                    status = ReviewStatusType.REJECTED
                    errors.append(
                        'Service signature of schema is invalid'
                    )

    return {
        'status': status,
        'errors': errors,
        'timestamp': datetime.utcnow().isoformat(),
    }
