'''
/network/member API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3

It takes 3 steps for a pod to become a member of service:
1: POST service/api/v1/service/member to get a CSR for a membersigned
2: PUT directory/api/v1/service/member to get the DNS record created
3: PUT service/api/v1/service/member to tell service that the pod with
   the membership is up and running
'''

from copy import copy
from logging import getLogger
from byoda.util.logger import Logger

from fastapi import APIRouter, Depends, Request
from fastapi import HTTPException

from cryptography import x509

from byoda.datatypes import IdType
from byoda.datatypes import MemberStatus
from byoda.datatypes import AuthSource
from byoda.datatypes import EntityId

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service

from byoda.datastore.certstore import CertStore
from byoda.datastore.memberdb import MemberDb

from byoda.secrets.secret import Secret
from byoda.secrets.membersca_secret import MembersCaSecret

from byoda.models import CertChainRequestModel
from byoda.models import CertSigningRequestModel
from byoda.models import SignedMemberCertResponseModel
from byoda.models.ipaddress import IpAddressResponseModel
from byoda.servers.service_server import ServiceServer

from byoda.util.paths import Paths

from byoda import config

from ..dependencies.memberrequest_auth import MemberRequestAuthFast
from ..dependencies.memberrequest_auth import MemberRequestAuthOptionalFast

_LOGGER: Logger = getLogger(__name__)

router: APIRouter = APIRouter(
    prefix='/api/v1/service',
    dependencies=[]
)


@router.post('/member', response_model=SignedMemberCertResponseModel,
             status_code=201)
async def post_member(request: Request, csr: CertSigningRequestModel,
                      auth: MemberRequestAuthOptionalFast =
                      Depends(MemberRequestAuthOptionalFast)
                      ):
    '''
    Submit a Certificate Signing Request for the Member certificate
    and get the cert signed by the Service Members CA
    This API is called by pods
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    server: ServiceServer = config.server
    member_db: MemberDb = server.member_db

    _LOGGER.debug(f'POST Member API called from {request.client.host}')

    await auth.authenticate()

    server: ServiceServer = config.server
    service: Service = server.service
    network: Network = server.network

    # Authorization
    csr_x509: x509 = Secret.csr_from_string(csr.csr)
    common_name: str = Secret.extract_commonname(csr_x509)

    try:
        csr_entity_id: EntityId = \
            MembersCaSecret.review_commonname_by_parameters(
                common_name, network.name, service.service_id
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

    if auth.is_authenticated:
        if auth.auth_source != AuthSource.CERT:
            raise HTTPException(
                status_code=401,
                detail=(
                    'When used with credentials, this API requires '
                    'authentication with a TLS client cert'
                )
            )

        if csr_entity_id.id_type != IdType.MEMBER:
            raise HTTPException(
                status_code=403,
                detail='A TLS cert of a member must be used with this API'
            )

        _LOGGER.debug(f'Signing csr for existing member {csr_entity_id.id}')
    else:
        # TODO: security: consider tracking member UUIDs to avoid
        # race condition between CSR signature and member registration
        # with the Directory server
        ips = server.dns_resolver.resolve(common_name)
        if ips:
            _LOGGER.debug(
                'Attempt to submit CSR for existing member without '
                'authentication'
            )
            raise HTTPException(
                status_code=401, detail=(
                    'Must use TLS client cert when renewing a member cert'
                )
            )
        _LOGGER.debug(f'Signing csr for new member {csr_entity_id.id}')
    # End of Authorization

    if csr_entity_id.service_id is None:
        raise ValueError(
            f'No service id found in common name {common_name}'
        )

    if csr_entity_id.service_id != service.service_id:
        raise HTTPException(
            404, f'Incorrect service_id in common name {common_name}'
        )

    # The Network Services CA signs the CSRs for Service CAs
    certstore = CertStore(service.members_ca)

    certchain = certstore.sign(
        csr.csr, IdType.MEMBER, request.client.host
    )

    # Get the certs as strings so we can return them
    signed_cert = certchain.cert_as_string()
    cert_chain = certchain.cert_chain_as_string()

    service_data_cert_chain = service.data_secret.cert_as_pem()

    _LOGGER.info(f'Signed certificate with commonname {common_name}')

    await member_db.add_meta(
        csr_entity_id.id, request.client.host, None, cert_chain,
        MemberStatus.SIGNED
    )

    return {
        'signed_cert': signed_cert,
        'cert_chain': cert_chain,
        'service_data_cert_chain': service_data_cert_chain,
    }


@router.put('/member/version/{schema_version}',
            response_model=IpAddressResponseModel)
async def put_member(request: Request, schema_version: int,
                     certchain: CertChainRequestModel,
                     auth: MemberRequestAuthFast = Depends(
                        MemberRequestAuthFast)):
    '''
    Registers a known pod with its IP address and its data cert
    '''

    server: ServiceServer = config.server
    member_db: MemberDb = server.member_db

    _LOGGER.debug(f'PUT Member API called from {request.client.host}')

    await auth.authenticate()

    network: Network = config.server.network
    service: Service = config.server.service

    if service.service_id != auth.service_id:
        _LOGGER.debug(
            f'Service ID {service.service_id} of PUT call does not match '
            f'service ID {auth.service_id} in client cert'
        )
        raise HTTPException(404)

    paths: Paths = copy(service.paths)

    member_data_secret = Secret(
        cert_file=paths.get(
            Paths.SERVICE_MEMBER_DATACERT_FILE, member_id=auth.member_id
        ),
        key_file=paths.get(
            Paths.MEMBER_DATA_KEY_FILE, service_id=auth.member_id
        ),
        storage_driver=network.paths.storage_driver
    )
    # from_string() concats the cert and the certchain together
    # so we can use it here with just providing the certchain parameter
    member_data_secret.from_string(certchain.certchain)

    await member_data_secret.save(overwrite=True)

    await member_db.add_meta(
        auth.member_id, auth.remote_addr, schema_version, certchain.certchain,
        MemberStatus.REGISTERED
    )

    _LOGGER.debug(
        f'Updating registration for member_id {auth.member_id} with '
        f'schema version {schema_version} and '
        f'remote address {auth.remote_addr}'
    )
    return {
        'ipv4_address': auth.remote_addr
    }
