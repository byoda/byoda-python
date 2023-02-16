'''
/network/account API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''


import logging

from fastapi import APIRouter, Depends, Request, HTTPException

from cryptography import x509

from byoda.datamodel.network import Network

from byoda.datatypes import IdType
from byoda.datatypes import AuthSource

from byoda.secrets.secret import Secret
from byoda.secrets.networkaccountsca_secret import NetworkAccountsCaSecret
from byoda.datastore.certstore import CertStore

from byoda.datastore.dnsdb import DnsDb
from byoda.datastore.dnsdb import DnsRecordType

from byoda.models import CertSigningRequestModel
from byoda.models import SignedAccountCertResponseModel
from byoda.models import IpAddressResponseModel

from byoda import config

from ..dependencies.accountrequest_auth import AccountRequestAuthFast
from ..dependencies.accountrequest_auth import AccountRequestOptionalAuthFast

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/network', dependencies=[])


@router.post(
    '/account', response_model=SignedAccountCertResponseModel,
    status_code=201
)
async def post_account(request: Request, csr: CertSigningRequestModel,
                       auth: AccountRequestOptionalAuthFast =
                       Depends(AccountRequestOptionalAuthFast)):
    '''
    Submit a Certificate Signing Request and get the signed
    certificate
    This API is called by pods
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy
    '''

    _LOGGER.debug(f'POST Account API called from {request.client.host}')

    await auth.authenticate()

    network: Network = config.server.network
    dnsdb: DnsDb = network.dnsdb

    # Authorization
    csr_x509: x509 = Secret.csr_from_string(csr.csr)
    common_name = Secret.extract_commonname(csr_x509)

    try:
        entity_id = NetworkAccountsCaSecret.review_commonname_by_parameters(
            common_name, network.name
        )
    except PermissionError:
        _LOGGER.debug(f'Invalid common name {common_name} in CSR')
        raise HTTPException(
            status_code=401, detail=f'Invalid common name {common_name} in CSR'
        )
    except (ValueError, KeyError) as exc:
        _LOGGER.debug(
                f'error when reviewing the common name {common_name} in your '
                f'CSR: {exc}'
        )
        raise HTTPException(
            status_code=400, detail=(
                f'error when reviewing the common name {common_name} in your '
                'CSR'
            )
        )

    try:
        await dnsdb.lookup_fqdn(
            common_name, DnsRecordType.A
        )
        dns_exists = True
    except KeyError:
        dns_exists = False

    if auth.is_authenticated:
        if auth.auth_source != AuthSource.CERT:
            _LOGGER.debug('This API does not accept JWTs')
            raise HTTPException(
                status_code=401,
                detail=(
                    'When used with credentials, this API requires '
                    'authentication with TLS client cert'
                )
            )

        if entity_id.id_type != IdType.ACCOUNT:
            raise HTTPException(
                status_code=403,
                detail='A TLS cert of an account must be used with this API'
            )

        if entity_id.id != auth.account_id:
            _LOGGER.debug(
                f'Common name {common_name} in CSR does not match the '
                'Account ID in the TLS client cert'
            )
            raise HTTPException(
                status_code=401, detail=(
                    f'Common name {common_name} in CSR does not match the '
                    'Account ID in the TLS client cert'
                )
            )

        _LOGGER.debug(f'Signing csr for existing account {entity_id.id}')
    else:
        if dns_exists:
            _LOGGER.debug(
                'Attempt to submit CSR for existing account without '
                'authentication '
            )
            raise HTTPException(
                status_code=401, detail=(
                    'Must use TLS client cert when renewing an account cert'
                )
            )
        _LOGGER.debug(f'Signing csr for new account {entity_id.id}')
    # End of authorization

    certstore = CertStore(network.accounts_ca)

    certchain = certstore.sign(
        csr.csr, IdType.ACCOUNT, request.client.host
    )

    signed_cert = certchain.cert_as_string()
    cert_chain = certchain.cert_chain_as_string()

    network_data_cert_chain = network.data_secret.cert_as_pem()

    if not dns_exists:
        await dnsdb.create_update(
            entity_id.id, IdType.ACCOUNT, auth.remote_addr
        )

    return {
        'signed_cert': signed_cert,
        'cert_chain': cert_chain,
        'network_data_cert_chain': network_data_cert_chain,
    }


@router.put('/account', response_model=IpAddressResponseModel)
async def put_account(request: Request, auth: AccountRequestAuthFast = Depends(
                AccountRequestAuthFast)):
    '''
    Creates/updates the DNS entry for the commonname in the TLS Client cert.
    '''

    _LOGGER.debug(f'Account PUT API called from IP {request.client.host}')

    await auth.authenticate()

    # Authorization for the request
    if not auth.is_authenticated:
        _LOGGER.debug('API called without authentication')
        raise HTTPException(
            status_code=401, detail='This API requires authentication'
        )
    # end of authorization

    dnsdb: DnsDb = config.server.network.dnsdb

    await dnsdb.create_update(
        auth.account_id, IdType.ACCOUNT, auth.remote_addr
    )

    return {
        'ipv4_address': auth.remote_addr
    }
