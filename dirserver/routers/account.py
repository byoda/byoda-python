'''
/network/account API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''


import logging

from fastapi import APIRouter, Depends, Request, HTTPException

from cryptography import x509

from byoda.datamodel.network import Network

from byoda.datatypes import IdType

from byoda.secrets.secret import Secret
from byoda.secrets.networkaccountsca_secret import NetworkAccountsCaSecret
from byoda.datastore.certstore import CertStore

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
def post_account(request: Request, csr: CertSigningRequestModel,
                 auth: AccountRequestAuthFast = Depends(AccountRequestAuthFast)
                 ):
    '''
    Submit a Certificate Signing Request and get the signed
    certificate
    This API is called by pods
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy
    '''

    _LOGGER.debug(f'POST Account API called from {request.client.host}')

    network: Network = config.server.network

    # Authorization
    csr_x509: x509 = Secret.csr_from_string(csr.csr)
    common_name = Secret.extract_commonname(csr_x509)
    try:
        entity_id = NetworkAccountsCaSecret.review_commonname_by_parameters(
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

    # Attacks through badly formatted common names in the secret are not possible
    # because entity_id.id is guaranteed to be an UUID and entity_id.id_type is
    # a value of the IdType enum
    file_path = (
        f'{network.paths.account_directory(entity_id.id)}'
        f'{entity_id.id_type.value}{entity_id.id}'
    )

    if auth.is_authenticated:
        if (entity_id.id_type != IdType.ACCOUNT
                or entity_id.id != auth.account_id):
            raise HTTPException(
                status_code=401, detail=(
                    f'Common name {common_name} in CSR does not match the '
                    'Account ID in the TLS client cert'
                )
            )
        _LOGGER.debug(f'Signing csr for existing account {entity_id.id}')
    else:

        if network.paths.storage_driver.exists(file_path):
            _LOGGER.debug('Attempt to submit CSR for existing account ')
            raise HTTPException(
                status_code=401, detail=(
                    'Must use TLS client cert or JWT when renewing an '
                    'account cert'
                )
            )
    # End of authorization

    certstore = CertStore(network.accounts_ca)

    certchain = certstore.sign(
        csr.csr, IdType.ACCOUNT, request.client.host
    )

    signed_cert = certchain.cert_as_string()
    cert_chain = certchain.cert_chain_as_string()

    network_data_cert_chain = network.data_secret.cert_as_pem()

    _LOGGER.debug(
        f'Persisting signing of account CSR for {entity_id.id}'
    )
    network.paths.storage_driver.write(file_path, common_name)

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

    _LOGGER.debug(f'Account PUT API called from IP {request.client.host}')

    # Authorization for the request
    if not auth.is_authenticated:
        raise HTTPException(
            status_code=401, detail='This API requires authentication'
        )
    # end of authorization

    network = config.server.network

    network.dnsdb.create_update(
        auth.account_id, IdType.ACCOUNT, auth.remote_addr
    )

    return {
        'ipv4_address': auth.remote_addr
    }
