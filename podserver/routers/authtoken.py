'''
/authtoken API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import os

from uuid import UUID
from logging import getLogger
from byoda.util.logger import Logger

from fastapi import APIRouter
from fastapi import Request
from fastapi import HTTPException

from passlib.context import CryptContext

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.datatypes import IdType

from byoda.requestauth.jwt import JWT

from byoda.models.authtoken import AuthRequestModel
from byoda.models.authtoken import AuthTokenResponseModel
from byoda.models.authtoken import AuthTokenRemoteRequestModel

from byoda.servers.pod_server import PodServer

from byoda.limits import MAX_APP_TOKEN_EXPIRATION

from byoda import config

from ..dependencies.pod_api_request_auth import AuthDep

_LOGGER: Logger = getLogger(__name__)

router: APIRouter = APIRouter(prefix='/api/v1/pod', dependencies=[])


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

    server: PodServer = config.server
    account: Account = server.account

    if not account.password:
        raise HTTPException(
            status_code=403,
            detail='Login using username/password disabled as no password '
            'was set'
        )

    username: str
    member: Member | None = None
    if auth_request.service_id:
        member = await account.get_membership(auth_request.service_id)
        if not member:
            raise HTTPException(
                status_code=401, detail='Invalid username/password'
            )
        username = os.environ.get('ACCOUNT_USERNAME', str(
            member.member_id)[:8]
        )
    else:
        username = os.environ.get(
            'ACCOUNT_USERNAME', str(account.account_id)[:8]
        )

    context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    password_verified: bool = context.verify(
        auth_request.password, account.password
    )
    if (auth_request.username != username
            or not password_verified):
        _LOGGER.warning(
            'Login with invalid password for '
            f'username {auth_request.username}'
        )
        raise HTTPException(
            status_code=401, detail='Invalid username/password'
        )

    data: dict[str, str | UUID | int | IdType] = {}
    jwt: JWT
    if auth_request.target_type == IdType.ACCOUNT:
        jwt = account.create_jwt()
        data['account_id'] = account.account_id
        data['id_type'] = IdType.ACCOUNT
    elif auth_request.target_type == IdType.MEMBER:
        if not auth_request.service_id:
            raise HTTPException(400, 'Missing service_id parameter')
        jwt = member.create_jwt()
        data['member_id'] = member.member_id
        data['id_type'] = IdType.MEMBER
    elif auth_request.target_type == IdType.SERVICE:
        if not auth_request.service_id:
            raise HTTPException('Missing service_id parameter')
        data['member_id'] = member.member_id
        data['id_type'] = IdType.MEMBER
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
        data['member_id'] = member.member_id
        data['id_type'] = IdType.MEMBER
    else:
        raise HTTPException(400, 'Invalid target for the JWT')

    data['auth_token'] = jwt.encoded
    return data


# BUG: this should be a GET?
@router.post('/authtoken/service_id/{service_id}',
             response_model=AuthTokenResponseModel,
             status_code=200)
async def post_member_auth_token(request: Request, service_id: int,
                                 auth: AuthDep):
    '''
    Get the JWT for a pod member, using account JWT
    '''

    server: PodServer = config.server
    account: Account = server.account

    _LOGGER.debug(
        f'POST Authtoken member API called from {request.client.host} '
        f'for service_id {service_id} and '
        f'with JWT: {auth.authorization is not None}'
    )

    await auth.authenticate(account)

    # Authorization: handled by PodApiRequestAuth, which checks account
    # cert / JWT was used and it matches the account ID of the pod

    member: Member = await account.get_membership(service_id)

    jwt: JWT = member.create_jwt()

    return {
        'auth_token': jwt.encoded,
        'member_id': member.member_id,
        'id_type': IdType.MEMBER
    }


@router.post('/authtoken/remote')
async def post_member_remote_auth_token(
        request: Request, remote: AuthTokenRemoteRequestModel, auth: AuthDep
        ) -> AuthTokenResponseModel:

    server: PodServer = config.server
    account: Account = server.account

    _LOGGER.debug(
        f'POST Authtoken member API called from {request.client.host} '
        f'for service_id {auth.service_id} and '
        f'with JWT: {auth.authorization is not None}'
    )

    await auth.authenticate(account, service_id=remote.service_id)

    if not auth.is_authenticated:
        raise HTTPException(
            status_code=401, detail='Invalid authentication'
        )

    if auth.service_id is None:
        raise HTTPException(
            status_code=400, detail='Service ID not provided'
        )

    if auth.id_type != IdType.MEMBER:
        raise HTTPException(
            status_code=401, detail='Not authorized to access this service'
        )

    member: Member = await account.get_membership(auth.service_id)

    jwt: JWT = member.create_jwt(
        target_id=remote.target_id, target_type=remote.target_type,
        expiration_seconds=MAX_APP_TOKEN_EXPIRATION
    )

    return {
        'auth_token': jwt.encoded,
        'member_id': member.member_id,
        'id_type': IdType.MEMBER
    }
