'''
/network/account api API

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''


import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, HTTPException

from byoda.datatypes import IdType

from byoda.datastore import CertStore

from byoda.models import Stats, StatsResponseModel
from byoda.models import CertSigningRequestModel, CertChainModel
from byoda.models import LetsEncryptSecretModel

from byoda import config

# from ..dependencies.logannotation import annotate_logs
from ..dependencies.accountrequest_auth import AccountRequestAuthFast

_LOGGER = logging.getLogger(__name__)

router = APIRouter(
    prefix='/api/v1/network',
    dependencies=[]
)


@router.get('/account', response_model=StatsResponseModel)
def get_account(request: Request,
                auth: AccountRequestAuthFast = Depends(
                    AccountRequestAuthFast
                )):
    '''
    Get account stats with a suggestion for an UUID.
    If the API call is made with a valid client M-TLS cert then the
    DNS entry for the commonname in the cert will be updated.
    '''

    network = config.server.network

    dns_update = False
    if auth.is_authenticated:
        _LOGGER.debug(
            f'GET Account API called with authentication from '
            f'{auth.remote_addr}'
        )
        dns_updates = network.dnsdb.create_update(
            auth.account_id, IdType.ACCOUNT, auth.remote_addr
        )
        if dns_updates:
            dns_update = True
        uuid = auth.account_id
    else:
        _LOGGER.debug(
            f'GET Account API called without authentication from '
            f'{auth.remote_addr}'
        )
        uuid = uuid4()

    stats = Stats(1, 2, uuid, '127.0.0.1', dns_update)
    return stats.as_dict()


@router.post('/account', response_model=CertChainModel)
def post_account(request: Request, csr: CertSigningRequestModel,
                 auth: AccountRequestAuthFast = Depends(
                     AccountRequestAuthFast)):
    '''
    Submit a Certificate Signing Request and get the signed
    certificate
    '''

    _LOGGER.debug(f'POST Account API called from {auth.remote_addr}')

    # if not auth.is_authenticated:
    #     raise HTTPException(
    #         status_code=401, detail='Unauthorized'
    #     )

    network = config.server.network

    certstore = CertStore(network.accounts_ca)

    certchain = certstore.sign(
        csr.csr, IdType.ACCOUNT, auth.remote_addr
    )

    return certchain.as_dict()


@router.put('/account')
def put_account(request: Request, secret: LetsEncryptSecretModel,
                auth: AccountRequestAuthFast = Depends(
                    AccountRequestAuthFast)):
    '''
    Submit a Certificate Signing Request and get the signed
    certificate
    '''

    _LOGGER.debug('POST Account API called')

    if not auth.is_authenticated:
        raise HTTPException(
            status_code=401, detail='Unauthorized'
        )

    network = config.server.network

    dns_updates = network.dnsdb.create_update(
        auth.account_id, IdType.ACCOUNT, auth.remote_addr, secret=secret.secret
    )

    if dns_updates:
        dns_updates = True
