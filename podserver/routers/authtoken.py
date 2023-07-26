'''
/authtoken API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''


import logging

from fastapi import APIRouter, Request, HTTPException, Depends

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.datatypes import IdType

from byoda.requestauth.jwt import JWT

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
    Get JWT the pod account
    '''

    _LOGGER.debug(
        f'POST Authtoken API called from {request.client.host} with '
        f'username {auth_request.username}, '
        f'with password: {auth_request.password is not None} '
        f'audience {auth_request.target_type.value}, '
        f'app_id {auth_request.app_id} '
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

    if auth_request.target_type == IdType.ACCOUNT:
        jwt = account.create_jwt()
    elif auth_request.target_type == IdType.MEMBER:
        if not auth_request.service_id:
            raise HTTPException(400, 'Missing service_id parameter')
        jwt = member.create_jwt()
    elif auth_request.target_type == IdType.SERVICE:
        if not auth_request.service_id:
            raise HTTPException('Missing service_id parameter')
        jwt = JWT.create(
            member.member_id, IdType.MEMBER, member.tls_secret,
            member.network.name, service_id=member.service_id,
            scope_type=auth_request.target_type, scope_id=member.service_id,
        )
    elif auth_request.target_type == IdType.APP:
        if not auth_request.service_id:
            raise HTTPException('Missing service_id parameter')

        if not auth_request.app_id:
            raise HTTPException('Missing app_id parameter')

        jwt = JWT.create(
            member.member_id, IdType.MEMBER, member.tls_secret,
            member.network.name, service_id=member.service_id,
            scope_type=auth_request.target_type, scope_id=auth_request.app_id,
        )
    else:
        raise HTTPException(400, 'Invalid target for the JWT')

    return {'auth_token': jwt.encoded}


@router.post('/authtoken/service_id/{service_id}',
             response_model=AuthTokenResponseModel,
             status_code=200)
async def post_member_auth_token(request: Request, service_id: int,
                                 auth: PodApiRequestAuth =
                                 Depends(PodApiRequestAuth)):
    '''
    Get the JWT for a pod member, using username/password
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
