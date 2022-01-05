'''
/network/account API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''


import logging

from fastapi import APIRouter, Depends, Request

from byoda.datatypes import IdType

from byoda.datastore import CertStore

from byoda.models import CertSigningRequestModel
from byoda.models import SignedAccountCertResponseModel
from byoda.models import IpAddressResponseModel
# from byoda.models import LetsEncryptSecretModel

from byoda import config

from ..dependencies.accountrequest_auth import AccountRequestAuthFast

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/network', dependencies=[])


@router.post(
    '/account', response_model=SignedAccountCertResponseModel,
    status_code=201
)
def post_account(request: Request, csr: CertSigningRequestModel):
    '''
    Submit a Certificate Signing Request and get the signed
    certificate
    This API is called by pods
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy
    '''

    _LOGGER.debug(f'POST Account API called from {request.client.host}')

    network = config.server.network

    certstore = CertStore(network.accounts_ca)

    certchain = certstore.sign(
        csr.csr, IdType.ACCOUNT, request.client.host
    )

    # TODO: SECURITY: check if the UUID is already in use
    signed_cert = certchain.cert_as_string()
    cert_chain = certchain.cert_chain_as_string()

    network_data_cert_chain = network.data_secret.cert_as_pem()
    return {
        'signed_cert': signed_cert,
        'cert_chain': cert_chain,
        'network_data_cert_chain': network_data_cert_chain,
    }


@router.put('/account', response_model=IpAddressResponseModel)
def put_account(request: Request, auth: AccountRequestAuthFast = Depends(
                AccountRequestAuthFast)):
    '''
    Get account stats with a suggestion for an UUID.
    If the API call is made with a valid client M-TLS cert then the
    DNS entry for the commonname in the cert will be updated.
    '''

    network = config.server.network

    network.dnsdb.create_update(
        auth.account_id, IdType.ACCOUNT, auth.remote_addr
    )

    return {
        'ipv4_address': auth.remote_addr
    }
