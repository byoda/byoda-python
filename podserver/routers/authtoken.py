'''
/authtoken API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''


import logging

from fastapi import APIRouter, Request, HTTPException, Depends

from fastapi.security import HTTPBasic, HTTPBasicCredentials

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.models import AuthTokenResponseModel

from byoda import config

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/pod', dependencies=[])

security = HTTPBasic()


@router.get(
    '/authtoken/service_id/{service_id}',
    response_model=AuthTokenResponseModel
)
async def get_member_authtoken(request: Request, service_id: int,
                               credentials: HTTPBasicCredentials
                               = Depends(security)):
    '''
    Get an authentication token for the membership

    :param service_id: service_id of the service
    :raises: HTTPException 404
    '''

    _LOGGER.debug(f'GET authtoken API called from {request.client.host}')

    account: Account = config.server.account

    if not account.password:
        raise HTTPException(
            status_code=403,
            detail='Basic Auth disabled as no password was set'
        )

    if (credentials.username != str(account.account_id)[:8]
            or credentials.password != account.password):
        _LOGGER.warning(
            'Basic auth with invalid password for '
            f'username {credentials.username}'
        )
        raise HTTPException(
            status_code=401, detail='Invalid username/password'
        )

    # Make sure we have the latest updates of memberships
    await account.load_memberships()

    member: Member = account.memberships.get(service_id)

    if not member:
        # We want to hide that te pod does not have a membership for the
        # specified service
        _LOGGER.warning(
            f'Basic auth attempted with username {credentials.username}'
            f'for service ID {service_id}'
        )
        raise HTTPException(
            status_code=401,
            detail='Invalid username/password'
        )

    jwt = member.create_jwt()
    _LOGGER.debug('Returning JWT')

    return {'auth_token': jwt.encoded}


@router.get(
    '/authtoken', response_model=AuthTokenResponseModel
)
async def get_account_authtoken(request: Request,
                                credentials: HTTPBasicCredentials =
                                Depends(security)):
    '''
    Get an authentication token for the account

    :raises: HTTPException 401, 403
    '''

    account: Account = config.server.account

    if not account.password:
        raise HTTPException(
            status_code=403,
            detail='Basic Auth disabled as no password was set'
        )

    if (credentials.username != str(account.account_id)[:8]
            or credentials.password != account.password):
        _LOGGER.warning(
            'Basic auth with invalid password for '
            f'username {credentials.username}'
        )
        if config.debug:
            _LOGGER.debug(
                f'Password provided {credentials.username} does not '
                f'match {account.password}'
            )
        raise HTTPException(
            status_code=401, detail='Invalid username/password'
        )

    jwt = account.create_jwt()
    return {'auth_token': jwt.encoded}
