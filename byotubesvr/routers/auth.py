'''
Authentication APIs for 'BYO.Tube-lite' service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from uuid import UUID
from typing import Annotated
from logging import getLogger

from fastapi import HTTPException
from fastapi import Depends
from fastapi import status
from fastapi import APIRouter
from fastapi import Request

from byoda.models.api_models import UserResponse
from byoda.models.api_models import Token

from byoda.models.db_models import dbServiceInstance

from byoda.datastore.sql_storage import SqlStorage

from byoda.jwt_auth import authenticate_account
from byoda.jwt_auth import create_access_token
from byoda.jwt_auth import get_current_active_account

from byoda.jwt_auth import OAuth2PasswordRequestForm

from byoda.clouds.deploy import DeployConfig

from byoda import config

_LOGGER = getLogger(__name__)

router = APIRouter(prefix='/api/v1/auth', dependencies=[])


@router.post("/token", response_model=Token)
async def login_for_access_token(
        form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    '''
    User authentication API
    '''

    account: dbAccount = await authenticate_account(
        form_data.username, form_data.password
    )

    if not account:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not account.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token: str = create_access_token(
        data={"sub": account.email}, secret_key=config.secret_key,
        is_refresh_token=False
    )

    # Refresh tokens to be implemented
    # refresh_token = create_access_token(
    #     data={"sub": user.email}, secret_key=config.secret_key,
    #     is_refresh_token=True
    # )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        # "refresh_token": refresh_token,
    }


@router.get("/users/me/", response_model=UserResponse)
async def read_users_me(
    request: Request,
    current_account: Annotated[dbAccount, Depends(get_current_active_account)]
):
    '''
    Return info about the account, including the pod account id
    '''

    _LOGGER.debug(
        f'Received request from {request.client.host} for getting '
        f'provisioning status for accound.id {current_account.id}'
    )
    deploy_config: DeployConfig = config.deploy_config
    sql_db: SqlStorage = deploy_config.sql_db_hosting
    service_instances: list[dbServiceInstance] = \
        await sql_db.get_service_instances_for_account(
            account_id=current_account.id
        )
    if len(service_instances) > 1:
        _LOGGER.info(
            f'Found more than one service instance for '
            f'account.id {current_account.id}, using the first one'
        )

    data: dict[str, str | bool | UUID] = {
        'account_id': current_account.account_id,
        'email': current_account.email,
        'is_enabled': current_account.is_enabled,
        'first_name': current_account.first_name,
        'family_name': current_account.family_name,
    }
    if service_instances:
        data['pod_account_id'] = service_instances[0].pod_account_id

    result: UserResponse = UserResponse.model_validate(data)
    return result


@router.get("/users/me/items/")
async def read_own_items(
    request: Request,
    current_account: Annotated[dbAccount, Depends(get_current_active_account)]
):
    '''
    Return info about the account, including the pod account id
    '''

    _LOGGER.debug(
        f'Received request from {request.client.host} for getting '
        f'provisioning status for accound.id {current_account.id}'
    )
    deploy_config: DeployConfig = config.deploy_config
    sql_db: SqlStorage = deploy_config.sql_db_hosting
    service_instances: list[dbServiceInstance] = \
        await sql_db.get_service_instances_for_account(
            account_id=current_account.id
        )
    if len(service_instances) > 1:
        _LOGGER.info(
            f'Found more than one service instance for '
            f'account.id {current_account.id}, using the first one'
        )

    data: dict[str, str | bool | UUID] = {
        'account_id': current_account.account_id,
        'email': current_account.email,
        'is_enabled': current_account.is_enabled,
        'first_name': current_account.first_name,
        'family_name': current_account.family_name,
    }
    if service_instances:
        data['pod_account_id'] = service_instances[0].pod_account_id

    result: UserResponse = UserResponse.model_validate(data)
    return result
