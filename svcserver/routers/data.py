'''
/service/data API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

from logging import getLogger

from fastapi import APIRouter
from fastapi import Request

from byoda.models.data_api_models import PageInfoResponse
from byoda.models.data_api_models import EdgeResponse
from byoda.models.data_api_models import QueryResponseModel

from byoda.datacache.asset_cache import AssetCache

from byoda.servers.service_server import ServiceServer

from byoda.util.logger import Logger

from byoda import config

_LOGGER: Logger = getLogger(__name__)

router: APIRouter = APIRouter(
    prefix='/api/v1/service',
    dependencies=[]
)

DEFAULT_PAGING_SIZE: int = 25

MAX_PAGE_SIZE: int = 100


@router.get('/data', status_code=200)
async def get_data(request: Request,
                   list_name: str | None = AssetCache.DEFAULT_ASSET_LIST,
                   first: int = DEFAULT_PAGING_SIZE, after: str | None = None,
                   ingest_status: str | None = None
                   ) -> QueryResponseModel:
    '''
    This API is called by pods

    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    _LOGGER.debug(f'GET Data API called from {request.client.host}')

    server: ServiceServer = config.server
    asset_cache: AssetCache = server.asset_cache

    first = min(first, MAX_PAGE_SIZE)

    filter_name: str | None = None
    if ingest_status:
        filter_name = 'ingest_status'

    edges: list[EdgeResponse] = await asset_cache.get_list_assets(
        list_name, after=after, first=first + 1,
        filter_name=filter_name, filter_value=ingest_status
    )

    has_next_page: bool = False
    if len(edges) > first:
        edges = edges[:-1]
        has_next_page = True

    end_cursor = None
    if edges and isinstance(edges, list) and len(edges) > 0:
        end_cursor: str | None = edges[-1].cursor

    page = PageInfoResponse(has_next_page=has_next_page, end_cursor=end_cursor)

    return QueryResponseModel(
        total_count=len(edges),
        edges=edges,
        page_info=page
    )
