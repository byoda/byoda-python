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
from byoda.datacache.asset_cache import AssetCacheItem

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
                   list_name: str | None = AssetCache.ASSET_UPLOADED_LIST,
                   first: int = DEFAULT_PAGING_SIZE, after: int = 0
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

    asset_items: list[AssetCacheItem] = await asset_cache.get_range(
        list_name, after, first + 1
    )

    end_cursor: str | None = None
    has_next_page: bool = False
    if len(asset_items) > first:
        end_cursor = asset_items[-1].cursor
        asset_items = asset_items[:-1]
        has_next_page = True

    edges: list[EdgeResponse] = []
    for item in asset_items:
        edge = EdgeResponse(
            node=item.node,
            cursor=item.cursor or '',
            origin=item.origin
        )
        edges.append(edge)

    page = PageInfoResponse(has_next_page=has_next_page, end_cursor=end_cursor)

    return QueryResponseModel(
        total_count=len(asset_items),
        edges=edges,
        page_info=page
    )
