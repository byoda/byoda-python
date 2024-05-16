'''
APIs for managing a BYO.Tube-lite account

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3

'''

from uuid import UUID
from uuid import uuid4
from logging import Logger
from logging import getLogger
from typing import Annotated

from fastapi import APIRouter
from fastapi import Request
from fastapi import HTTPException
from fastapi import Depends

from fastapi.responses import ORJSONResponse

from fastapi_limiter.depends import RateLimiter

from byoda import config

from byotubesvr.datamodel.email import EmailVerificationMessage

from byotubesvr.auth.lite_jwt import LiteJWT
from byotubesvr.auth.lite_app_jwt import LiteAppJWT

from byotubesvr.auth.password import verify_password
from byotubesvr.auth.request_auth import LiteRequestAuth

from ..models.lite_account import LiteAccountSqlModel
from ..models.lite_account import LiteAccountApiModel
from ..models.lite_account import LiteAccountApiResponseModel
from ..models.lite_account import LiteAuthApiModel
from ..models.lite_account import LiteAuthApiResponseModel
from ..models.lite_account import LiteStatusApiResponseModel

from ..database.sql import SqlStorage

_LOGGER: Logger = getLogger(__name__)


ALGORITHM: str = "HS256"

ACCESS_TOKEN_EXPIRE_MINUTES: int = 18008        # 7 days

router = APIRouter(prefix='/api/v1/lite/account', dependencies=[])


@router.post('/signup', response_class=ORJSONResponse, dependencies=[
        Depends(RateLimiter(times=1, seconds=10)),
        Depends(RateLimiter(times=100, seconds=86400)),
    ]
)
async def create_account(request: Request, account: LiteAccountApiModel
                         ) -> LiteAccountApiResponseModel:
    '''
    Create a new BYO.Tube-lite account
    '''

    lite_db: SqlStorage = config.lite_db

    _LOGGER.debug(
        f'Request from {request.client.host} '
        f'to create account: {account.email}'
    )

    existing_account: LiteAccountSqlModel | None = \
        await LiteAccountSqlModel.from_db_by_email(
            lite_db, account.email
        )

    if existing_account:
        raise HTTPException(
            status_code=400,
            detail=f'Account for {account.email} already exists'
        )

    account = LiteAccountSqlModel.from_api_model(account, lite_db=lite_db)
    account.lite_id = uuid4()

    try:
        await account.persist(all_fields=True)
    except ValueError as exc:
        _LOGGER.error(f'Failed to create account: {exc}')
        raise HTTPException(status_code=400, detail='Failed to create account')

    resp: LiteAccountApiResponseModel = \
        LiteAccountApiResponseModel.from_sql_model(
            account, config.verification_url
        )

    _LOGGER.debug(
        f'Setting verification URL: {resp.verification_url} '
        f'for email {account.email} and lite_id {account.lite_id}'
    )

    verification_url: str = resp.verification_url
    verification_email = EmailVerificationMessage(
        sender='byotubesvr/api/v1/lite/account/signup',
        subject='Email verification for BYO.Tube',
        recipient_name='',
        recipient_email=f'{account.email}',
        sender_address='DoNotReply@byo.tube',
        verification_url=verification_url,
    )
    await verification_email.to_queue(config.email_queue)

    if not config.debug or not config.test_case:
        # Make sure we do not return the verification url to the client
        # unless we run from a test case
        resp.verification_url = None

    return resp


@router.get('/verify', response_class=ORJSONResponse)
async def verify_email(request: Request, lite_id: UUID, token: str) -> dict:
    '''
    Verify a BYO.Tube-lite account
    '''

    lite_db: SqlStorage = config.lite_db
    _LOGGER.debug(
        f'Request from {request.client.host} '
        f'to verify Lite account: {lite_id}'
    )

    account: LiteAccountSqlModel | list[LiteAccountSqlModel] | None = \
        await LiteAccountSqlModel.from_db(lite_db, lite_id)

    if not account:
        raise HTTPException(
            status_code=404, detail=f'Account {lite_id} not found'
        )

    if isinstance(account, list):
        _LOGGER.exception(f'Multiple accounts found for lite_id {lite_id}')
        raise HTTPException(
            status_code=500, detail='Unexpected data encountered'
        )

    if account.is_enabled is False:
        raise HTTPException(
            status_code=403, detail='Account is disabled'
        )

    generated_token: str = account.generate_verification_token()
    if token != generated_token:
        _LOGGER.debug(
            f'Failed to verify email for {account.email}, {lite_id}: '
            f'token {token} does not match {generated_token}'
        )
        raise HTTPException(status_code=403, detail='Failed to verify account')

    account.is_verified = True
    account.is_enabled = True
    await account.persist(all_fields=False)

    return {'status': 'enabled'}


@router.post("/auth", response_class=ORJSONResponse)
async def auth_token(request: Request, auth_request: LiteAuthApiModel,
                     dependencies=[Depends(RateLimiter(times=2, seconds=5))]
                     ) -> LiteAuthApiResponseModel:
    '''
    User authentication API
    '''

    lite_db: SqlStorage = config.lite_db

    _LOGGER.debug(
        f'Request from {request.client.host} '
        f'to authenticate account {auth_request.email}'
    )

    account: LiteAccountSqlModel | None = \
        await LiteAccountSqlModel.from_db_by_email(lite_db, auth_request.email)

    if not account:
        raise HTTPException(
            status_code=403, detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    verified: bool = verify_password(
        auth_request.password.get_secret_value(), account.hashed_password
    )
    if not verified:
        raise HTTPException(
            status_code=403, detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not account.is_enabled:
        raise HTTPException(
            status_code=403, detail="User is disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jwt = LiteJWT()
    auth_token: str = jwt.create_auth_token(account.lite_id, account.is_funded)

    return {
        "auth_token": auth_token,
        "token_type": "bearer",
    }

AuthDep = Annotated[LiteRequestAuth, Depends(LiteRequestAuth)]


@router.post('/app_token', response_class=ORJSONResponse, status_code=201)
async def app_token(request: Request, app_id: UUID, auth: AuthDep) -> dict:
    '''
    API for getting a JWT for authentication against a 3rd party app
    '''

    _LOGGER.debug(
        f'Request from {request.client.host} with '
        f'LiteID {auth.lite_id} for status'
    )

    lite_db: SqlStorage = config.lite_db
    account: LiteAccountSqlModel | None = await LiteAccountSqlModel.from_db(
        lite_db, auth.lite_id
    )

    if not account:
        raise HTTPException(status_code=404, detail='Account not found')

    if account.is_enabled is False:
        raise HTTPException(status_code=403, detail='Account is disabled')

    auth_token: str = LiteAppJWT.create_auth_token(
        account.lite_id, app_id=app_id
    )

    return {
        'auth_token': auth_token,
        'token_type': 'bearer',
        'app_id': app_id
    }


@router.get('/status', response_class=ORJSONResponse)
async def status(request: Request, auth: AuthDep
                 ) -> LiteStatusApiResponseModel:
    '''
    Status API
    '''

    _LOGGER.debug(
        f'Request from {request.client.host} with '
        f'LiteID {auth.lite_id} for status'
    )

    lite_db: SqlStorage = config.lite_db
    account: LiteAccountSqlModel | None = await LiteAccountSqlModel.from_db(
        lite_db, auth.lite_id
    )

    if not account:
        raise HTTPException(status_code=404, detail='Account not found')

    if account.is_enabled is None:
        raise HTTPException(status_code=403, detail='Account is not verified')

    if account.is_enabled is False:
        raise HTTPException(status_code=403, detail='Account is disabled')

    status: str = 'ok'
    if account.is_funded is True:
        status = 'funded'

    return LiteStatusApiResponseModel(
        status=status, is_funded=account.is_funded, balance_points=0
    )
