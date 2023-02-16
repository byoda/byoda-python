'''
/network/service API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
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

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import HTTPException

from cryptography import x509

from byoda.datamodel.service import RegistrationStatus
from byoda.datastore.dnsdb import DnsRecordType
from byoda.servers.server import Server

from byoda.datatypes import IdType, ReviewStatusType
from byoda.datatypes import AuthSource

from byoda.datamodel.service import Service
from byoda.datamodel.schema import Schema
from byoda.servers.directory_server import DirectoryServer
from byoda.datamodel.network import Network

from byoda.models import ServiceSummariesModel
from byoda.models import CertChainRequestModel
from byoda.models import CertSigningRequestModel
from byoda.models import SignedServiceCertResponseModel
from byoda.models import SchemaModel, SchemaResponseModel
from byoda.models.ipaddress import IpAddressResponseModel

from byoda.datastore.certstore import CertStore
from byoda.datastore.dnsdb import DnsDb

from byoda.secrets import Secret
from byoda.secrets import ServiceCaSecret
from byoda.secrets import ServiceDataSecret
from byoda.secrets import NetworkServicesCaSecret

from byoda.util.paths import Paths
from byoda.util.message_signature import SignatureType

from byoda import config


from dirserver.dependencies.servicerequest_auth import ServiceRequestAuthFast
from dirserver.dependencies.servicerequest_auth import \
    ServiceRequestOptionalAuthFast

_LOGGER = logging.getLogger(__name__)

MAX_SERVICE_LIST = 100

router = APIRouter(
    prefix='/api/v1/network',
    dependencies=[]
)


@router.get('/services', response_model=ServiceSummariesModel)
async def get_services(request: Request, skip: int = 0, count: int = 0):
    '''
    Get a list of summaries of the available services. This API is called by
    pods.

    This API does not require authentication as service schemas are public
    information
    '''

    _LOGGER.debug(
        f'GET Services API called from {request.client.host} with pagination '
        f'skip {skip} and count {count}'
    )

    server: DirectoryServer = config.server
    network: Network = config.server.network

    await server.get_registered_services()

    _LOGGER.debug(f'We now have {len(network.services)} services in memory')

    if count == 0:
        count = min(len(network.services), MAX_SERVICE_LIST)

    services = list(network.services.values())
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
            } for service in services[skip: skip + count]
            if service.schema and service.schema.version
        ]
    }

    return result


@router.get('/service/service_id/{service_id}', response_model=SchemaModel)
async def get_service(request: Request, service_id: int):
    '''
    Get the data contract of the specified service.

    This API does not require authentication or authorization as service
    schemas are public information
    '''

    _LOGGER.debug(f'GET Service API called from {request.client.host}')

    server: Server = config.server
    network: Network = config.server.network

    await server.get_registered_services()

    _LOGGER.debug(f'We now have {len(network.services)} services in memory')

    if service_id not in network.services:
        # So this worker process does not know about the service. Let's
        # see if a CSR for the service secret has previously been signed
        # and the resulting cert saved
        if not await Service.is_registered(service_id):
            raise ValueError(f'Request for unknown service: {service_id}')

        service = network.add_service(service_id)
    else:
        service = network.services.get(service_id)
        if service is None:
            raise ValueError(f'Unkown service id: {service_id}')

        if not service.schema:
            service.registration_status = \
                await service.get_registration_status()
            if service.registration_status == RegistrationStatus.SchemaSigned:
                filepath = network.paths.get(
                    Paths.SERVICE_FILE, service_id=service_id
                )
                await service.load_schema(filepath)

    if not service.schema:
        raise HTTPException(404, f'Service {service_id} not found')

    return service.schema.json_schema


@router.post(
    '/service', response_model=SignedServiceCertResponseModel, status_code=201
)
async def post_service(request: Request, csr: CertSigningRequestModel,
                       auth: ServiceRequestOptionalAuthFast =
                       Depends(ServiceRequestOptionalAuthFast)):
    '''
    Submit a Certificate Signing Request for the ServiceCA certificate
    and get the cert signed by the network services CA
    This API is called by services
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy
    '''

    _LOGGER.debug(f'POST Service API called from {request.client.host}')

    network = config.server.network
    dnsdb: DnsDb = config.server.network.dnsdb

    # Authorization
    csr_x509: x509 = Secret.csr_from_string(csr.csr)
    common_name = Secret.extract_commonname(csr_x509)

    try:
        entity_id = NetworkServicesCaSecret.review_commonname_by_parameters(
            common_name, network.name
        )
    except PermissionError:
        raise HTTPException(
            status_code=401, detail=f'Invalid common name {common_name} in CSR'
        )
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=400, detail=(
                f'error when reviewing the common name {common_name} in your '
                'CSR'
            )
        )

    _LOGGER.debug(
        'POST service API called with CSR for service ID: '
        f'{entity_id.service_id}'
    )

    try:
        await dnsdb.lookup_fqdn(common_name, DnsRecordType.A)
        dns_exists = True
    except KeyError:
        dns_exists = False

    if auth.is_authenticated:
        if auth.auth_source != AuthSource.CERT:
            raise HTTPException(
                status_code=401,
                detail=(
                    'When used with credentials, this API requires '
                    'authentication with TLS client cert'
                )
            )

        if auth.id_type != IdType.SERVICE:
            raise HTTPException(
                status_code=401,
                detail='A TLS cert of a service is required for this API'
            )
        if auth.service_id != entity_id.service_id:
            raise HTTPException(
                status_code=403,
                detail=(
                    f'Client auth for service id {auth.service_id} does not '
                    f'match CSR for service_id {entity_id.service_id}'
                )
            )
    else:
        if dns_exists:
            raise HTTPException(
                status_code=403,
                detail=(
                    'CSR is for existing service, must use TLS Client cert '
                    'for authentication'
                )
            )
    # End of Authorization

    # The Network Services CA signs the CSRs for Service CAs
    certstore = CertStore(network.services_ca)

    certchain = certstore.sign(
        csr.csr, IdType.SERVICE_CA, request.client.host
    )

    # Create the service and add it to the network
    service = Service(network=network, service_id=entity_id.service_id)
    network.services[entity_id.service_id] = service

    # Get the certs as strings so we can return them
    signed_cert = certchain.cert_as_string()
    cert_chain = certchain.cert_chain_as_string()

    # We save the public key in the network directory tree. Not sure
    # if we actually need to do this as we can check any cert of the service
    # and its members through the cert chain that is chained to the network
    # root CA
    service.service_ca = ServiceCaSecret(service.service_id, network)
    service.service_ca.cert = certchain.signed_cert
    service.service_ca.cert_chain = certchain.cert_chain

    # If someone else already registered a Service then saving the cert will
    # raise an exception
    try:
        await service.service_ca.save(overwrite=False)
    except PermissionError:
        raise HTTPException(409, 'Service CA certificate already exists')

    # We create the DNS entry if it not exists yet to make sure there is no
    # race condition between submitting the CSR through the POST API and
    # registering the service server through the PUT API
    if not dns_exists:
        await dnsdb.create_update(
            None, IdType.SERVICE, auth.remote_addr,
            service_id=entity_id.service_id
        )

    data_cert = network.data_secret.cert_as_pem()

    return {
        'signed_cert': signed_cert,
        'cert_chain': cert_chain,
        'network_data_cert_chain': data_cert,
    }


@router.put('/service/service_id/{service_id}',
            response_model=IpAddressResponseModel)
async def put_service(request: Request, service_id: int,
                      certchain: CertChainRequestModel,
                      auth: ServiceRequestAuthFast = Depends(
                          ServiceRequestAuthFast)):
    '''
    Registers a known service with its IP address and its data cert
    '''

    _LOGGER.debug(f'PUT Service API called from {request.client.host}')

    await auth.authenticate()

    network: Network = config.server.network
    dnsdb: DnsDb = config.server.network.dnsdb

    if service_id != auth.service_id:
        raise ValueError(
            f'Service ID {service_id} of PUT call does not match '
            f'service ID {auth.service_id} in client cert'
        )

    if service_id not in network.services:
        # So this worker process does not know about the service. Let's
        # see if a CSR for the service secret has previously been signed
        # and the resulting cert saved
        if not await Service.is_registered(service_id):
            raise ValueError(f'Registration for unknown service: {service_id}')

        service = Service(network, service_id=service_id)
        service.registration_status = RegistrationStatus.CsrSigned
        network.services[service_id] = service
    else:
        service = network.services.get(service_id)
        if service is None:
            raise ValueError(f'Unkown service id: {service_id}')

    if not service.data_secret:
        service.data_secret = ServiceDataSecret(service_id, network)

    service.data_secret.from_string(certchain.certchain)

    await service.data_secret.save(overwrite=True)

    _LOGGER.debug(
        f'Updating registration for service id {service_id} with remote'
        f'address {auth.remote_addr}'
    )

    await dnsdb.create_update(
        None, IdType.SERVICE, auth.remote_addr,
        service_id=service_id
    )

    return {
        'ipv4_address': auth.remote_addr
    }


@router.patch('/service/service_id/{service_id}',
              response_model=SchemaResponseModel)
async def patch_service(request: Request, schema: SchemaModel, service_id: int,
                        auth: ServiceRequestAuthFast = Depends(
                            ServiceRequestAuthFast)):
    '''
    Submit a new (revision of a) service schema, aka data contract
    for signing with the Network Data secret
    This API is called by services

    '''

    _LOGGER.debug(f'PATCH Service API called from {request.client.host}')

    await auth.authenticate()

    # Authorize the request
    if service_id != auth.service_id:
        raise HTTPException(
            401, 'Service ID query parameter does not match the client cert'
        )

    if service_id != schema.service_id:
        raise HTTPException(
            403, f'Service_ID query parameter {service_id} does not match '
            f'the ServiceID parameter in the schema {schema.service_id}'
        )
    # End of authorization

    network: Network = config.server.network

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
            if not await Service.is_registered(service_id):
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
            if service.schema and schema.version <= service.schema.version:
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
                        await service.data_secret.load(with_private_key=False)

                    service_contract.verify_signature(
                        service.data_secret, SignatureType.SERVICE
                    )
                    service.schema = service_contract
                    service.schema.create_signature(
                        network.data_secret, SignatureType.NETWORK
                    )
                    storage_driver = network.paths.storage_driver
                    filepath = network.paths.get(Paths.SERVICE_FILE)
                    await service_contract.save(filepath, storage_driver)
                except ValueError:
                    status = ReviewStatusType.REJECTED
                    errors.append(
                        'Service signature of schema is invalid'
                    )

    return {
        'status': status,
        'errors': errors,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
