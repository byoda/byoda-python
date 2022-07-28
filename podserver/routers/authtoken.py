'''
/authtoken API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''


import logging

from fastapi import APIRouter, Request, HTTPException, Depends

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member


from byoda.models import AuthRequestModel
from byoda.models import AuthTokenResponseModel

from byoda import config

from ..dependencies.pod_api_request_auth import PodApiRequestAuth

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/pod', dependencies=[])


@router.post('/authtoken', response_model=AuthTokenResponseModel,
             status_code=200)
async def post_authtoken(request: Request, auth_request: AuthRequestModel):
    '''
    Get JWT for either a pod account or a pod member, if the service_id
    parameter was specified
    '''

    _LOGGER.debug(
        f'POST Authtoken API called from {request.client.host} with '
        f'username {auth_request.username}, '
        f'with password {auth_request.password is not None}'
        f'and service_id {auth_request.service_id}'
    )
    account: Account = config.server.account

    if not account.password:
        raise HTTPException(
            status_code=403,
            detail='Login using username/password disabled as no password '
            'was set'
        )

    if auth_request.service_id:
        await account.load_memberships()
        member: Member = account.memberships.get(auth_request.service_id)
        if not member:
            raise HTTPException(
                status_code=401, detail='Invalid username/password'
            )
        username = str(member.member_id)[:8]
    else:
        username = str(account.account_id)[:8]

    if (auth_request.username != username
            or auth_request.password != account.password):
        _LOGGER.warning(
            'Login with invalid password for '
            f'username {username}'
        )
        raise HTTPException(
            status_code=401, detail='Invalid username/password'
        )

    if auth_request.service_id:
        jwt = member.create_jwt()
    else:
        jwt = account.create_jwt()

    return {'auth_token': jwt.encoded}


@router.post('/authtoken/service_id/{service_id}',
             response_model=AuthTokenResponseModel,
             status_code=200)
async def post_member_auth_token(request: Request, service_id: int,
                                 auth: PodApiRequestAuth =
                                 Depends(PodApiRequestAuth)):
    '''
    Get data for the pod account.
    The data request is evaluated using the identify specified in the
    client cert.
    '''

    _LOGGER.debug(
        f'POST Authtoken member API called from {request.client.host} '
        f'for service_id {service_id} and '
        f'with JWT: {auth.authorization is not None}'
    )

    await auth.authenticate()

    # Authorization: handled by PodApiRequestAuth, which checks account
    # cert / JWT was used and it matches the account ID of the pod

    account: Account = config.server.account
    await account.load_memberships()
    member: Member = account.memberships.get(service_id)

    jwt = member.create_jwt()

    return {'auth_token': jwt.encoded}
