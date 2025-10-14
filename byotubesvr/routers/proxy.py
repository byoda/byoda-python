'''
proxy APIs to enable BT Lite accounts to interact with pods

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from typing import Annotated
from logging import Logger
from logging import getLogger

from fastapi import Request
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Depends

from byoda.models.data_api_models import ProxyQueryModel
from byoda.models.data_api_models import QueryResponseModel
from byoda.models.data_api_models import ProxyAppendModel

from byoda.datatypes import IdType
from byoda.datatypes import DataRequestType

from byoda.secrets.secret import Secret

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.data_api_client import HttpResponse

from byoda import config

from byotubesvr.auth.request_auth import LiteRequestAuth

_LOGGER: Logger = getLogger(__name__)

router: APIRouter = APIRouter(prefix='/api/v1/lite', dependencies=[])

AuthDep = Annotated[LiteRequestAuth, Depends(LiteRequestAuth)]


@router.post('/proxy/query', status_code=200)
async def query_proxy(request: Request, query: ProxyQueryModel, auth: AuthDep
                      ) -> QueryResponseModel:

    log_data: dict[str, str] = query.model_dump() | {
        'action': 'query',
        'remote_addr': request.client.host,
        'auth_id': auth.lite_id,
        'auth_id_type': IdType.BTLITE
    }

    _LOGGER.debug('Received query', extra=log_data)

    secret: Secret = config.service_secret

    resp: HttpResponse = await DataApiClient.call(
        config.SERVICE_ID, query.data_class, DataRequestType.QUERY,
        data=query.model_dump(), secret=secret,
        member_id=query.remote_member_id
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    data = resp.json()
    return data


@router.post('/proxy/append', status_code=201)
async def append_proxy(request: Request, append: ProxyAppendModel,
                       auth: AuthDep) -> int:

    log_data: dict[str, str] = append.model_dump() | {
        'action': 'append',
        'remote_addr': request.client.host,
        'auth_id': auth.lite_id,
        'auth_id_type': IdType.BTLITE
    }

    _LOGGER.debug('Received append', extra=log_data)

    secret: Secret = config.service_secret

    append_data = append.data
    resp: HttpResponse = await DataApiClient.call(
        config.SERVICE_ID, append.data_class, DataRequestType.APPEND,
        query_id=append.query_id,
        data={'data': append_data}, secret=secret,
        member_id=append.remote_member_id
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    return resp.text

