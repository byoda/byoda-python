'''
APIs for managing a BYO.Tube-lite account

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3

'''

from uuid import uuid4
from logging import Logger
from logging import getLogger
from typing import Annotated

from fastapi import APIRouter
from fastapi import Request
from fastapi import Depends
from fastapi import HTTPException

from byoda import config

from ..models.lite_account import LiteAccountSqlModel
from ..models.lite_account import LiteAccountApiModel
from ..models.lite_account import LiteAccountApiResponseModel

from ..database.sql import SqlStorage

_LOGGER: Logger = getLogger(__name__)

router = APIRouter(prefix='/api/v1/lite/account', dependencies=[])


@router.post('/signup')
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
        account, f'{request.base_url}/api/v1/lite/account/verify'
    )
    _LOGGER.debug(
        f'Setting verification URL: {resp.verification_url} '
        f'for email {account.email} and lite_id {account.lite_id}'
    )

    return resp
