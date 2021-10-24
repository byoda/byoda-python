'''
/network/member API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3

It takes 3 steps for a pod to become a member of service:
1: POST service/api/v1/service/member to get a CSR for a membersigned
2: PUT directory/api/v1/service/member to get the DNS record created
3: PUT service/api/v1/service/member to tell service that the pod with
   the membership is up and running
'''


import logging

from fastapi import APIRouter, Depends, Request
from fastapi import HTTPException

from byoda.datatypes import IdType

from byoda.datamodel import Network
from byoda.datamodel import Service
from byoda.datastore import CertStore

from byoda.models import CertChainRequestModel
from byoda.models import CertSigningRequestModel
from byoda.models import SignedCertResponseModel
from byoda.models.ipaddress import IpAddressResponseModel

from byoda.secrets import Secret
from byoda.secrets import MemberSecret

from byoda.util import Paths

from byoda import config

from ..dependencies.memberrequest_auth import MemberRequestAuthFast

_LOGGER = logging.getLogger(__name__)

router = APIRouter(
    prefix='/api/v1/service',
    dependencies=[]
)


@router.post('/member', response_model=SignedCertResponseModel)
def post_member(request: Request, csr: CertSigningRequestModel):
    '''
    Submit a Certificate Signing Request for the Member certificate
    and get the cert signed by the Service Members CA
    This API is called by pods
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    _LOGGER.debug(f'POST Member API called from {request.client.host}')

    service: Service = config.server.service
    network: Network = config.server.network

    # The Network Services CA signs the CSRs for Service CAs
    certstore = CertStore(service.members_ca)

    # We sign the cert first, then extract the service ID from the
    # signed cert and check if the service with the service ID already
    # exists.
    # TODO: extract common name from the CSR so that this code will
    # have a more logical flow where we check first before we sign
    certchain = certstore.sign(
        csr.csr, IdType.Member, request.client.host
    )

    # We make sure the key for the services in the network exists, even if
    # the schema for the service has not yet been provided through the PATCH
    # API
    commonname = MemberSecret.extract_commonname(certchain.signed_cert)
    entity_id = Secret.review_commonname_by_parameters(
        commonname, network.name, uuid_identifier=False,
        check_service_id=False
    )

    service_id = entity_id.service_id
    if service_id is None:
        raise ValueError(
            f'No service id found in common name {commonname}'
        )

    if service_id != service.service_id:
        raise HTTPException(
            404, f'Incorrect service_id in common name {commonname}'
        )

    # Get the certs as strings so we can return them
    signed_cert = certchain.cert_as_string()
    cert_chain = certchain.cert_chain_as_string()

    data_cert = service.data_secret.cert_as_pem()

    _LOGGER.info(f'Signed certificate with commonname {commonname}')

    return {
        'signed_cert': signed_cert,
        'cert_chain': cert_chain,
        'data_cert': data_cert,
    }


@router.put('/member/{service_id}', response_model=IpAddressResponseModel)
def put_member(request: Request,
               certchain: CertChainRequestModel,
               auth: MemberRequestAuthFast = Depends(
                   MemberRequestAuthFast)):
    '''
    Registers a known pod with its IP address and its data cert
    '''

    _LOGGER.debug(f'PUT Member API called from {request.client.host}')

    network = config.server.network
    service = config.server.service

    if service.service_id != auth.service_id:
        _LOGGER.debug(
            f'Service ID {service.service_id} of PUT call does not match '
            f'service ID {auth.service_id} in client cert'
        )
        raise HTTPException(404)

    paths = network.paths
    # We use a trick here to make sure we get unique filenames for the
    # member data secret by replacing the service_id in the template
    # with the member_id
    member_data_secret = Secret(
        cert_file=paths.get(
            Paths.MEMBER_DATA_CERT_FILE, account='pod',
            service_id=auth.member_id
        ),
        key_file=paths.get(
            Paths.MEMBER_DATA_KEY_FILE, account='pod',
            service_id=auth.member_id
        ),
        storage_driver=network.paths.storage_driver
    )
    # from_string() concats the cert and the certchain together
    # so we can use it here with just providing the certchain parameter
    member_data_secret.from_string(certchain.certchain)
    member_data_secret.save(overwrite=True)

    _LOGGER.debug(
        f'Updating registration for member_id {auth.member_id} with '
        f'remote address {auth.remote_addr}'
    )
    return {
        'ipv4_address': auth.remote_addr
    }
