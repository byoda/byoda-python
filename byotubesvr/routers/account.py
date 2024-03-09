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

from fastapi import APIRouter
from fastapi import Request
from fastapi import HTTPException
from fastapi import Depends
from fastapi.responses import ORJSONResponse

from fastapi_limiter.depends import RateLimiter

from byoda import config

from ..models.lite_account import LiteAccountSqlModel
from ..models.lite_account import LiteAccountApiModel
from ..models.lite_account import LiteAccountApiResponseModel

from ..database.sql import SqlStorage

_LOGGER: Logger = getLogger(__name__)

router = APIRouter(prefix='/api/v1/lite/account', dependencies=[])


@router.post('/signup', response_class=ORJSONResponse, dependencies=[
        Depends(RateLimiter(times=1, seconds=10)),
        Depends(RateLimiter(times=3, seconds=86400)),
    ]
)
async def create_account(request: Request, account: LiteAccountApiModel
                         ) -> LiteAccountApiResponseModel:
    '''
    Create a new BYO.Tube-lite account
    '''

    sql_db: SqlStorage = config.sql_db
    _LOGGER.debug(
        f'Request from {request.client.host} '
        f'to create account: {account.email}'
    )
    account = LiteAccountSqlModel.from_api_model(account, sql_db=sql_db)
    account.lite_id = uuid4()

    try:
        await account.persist(all_fields=True)
    except ValueError as exc:
        _LOGGER.error(f'Failed to create account: {exc}')
        raise HTTPException(status_code=400, detail='Failed to create account')

    resp = LiteAccountApiResponseModel.from_sql_model(
        account,
        f'{str(request.base_url).rstrip("/")}/api/v1/lite/account/verify'
    )
    _LOGGER.debug(
        f'Setting verification URL: {resp.verification_url} '
        f'for email {account.email} and lite_id {account.lite_id}'
    )

    return resp


@router.get('/verify', response_class=ORJSONResponse)
async def verify_email(request: Request, lite_id: UUID, token: str) -> dict:
    '''
    Verify a BYO.Tube-lite account
    '''

    sql_db: SqlStorage = config.sql_db
    _LOGGER.debug(
        f'Request from {request.client.host} '
        f'to verify Lite account: {lite_id}'
    )

    account: LiteAccountSqlModel | list[LiteAccountSqlModel] | None = \
        await LiteAccountSqlModel.from_db(sql_db, lite_id)

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
