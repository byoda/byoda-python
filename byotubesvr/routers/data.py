'''
/service/data API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023, 2024
:license    : GPLv3
'''

from uuid import UUID
from logging import getLogger, Logger

from fastapi import APIRouter
from fastapi import Request
from fastapi import HTTPException
from fastapi.responses import ORJSONResponse

from byoda.models.data_api_models import Channel
from byoda.models.data_api_models import PageInfoResponse
from byoda.models.data_api_models import EdgeResponse
from byoda.models.data_api_models import QueryResponseModel
from byoda.models.data_api_models import ChannelShortcutResponse
from byoda.models.data_api_models import ChannelShortcutValueResponseModel

from byoda.datacache.asset_cache import AssetCache
from byoda.datacache.channel_cache import ChannelCache

from byoda import config

_LOGGER: Logger = getLogger(__name__)

router: APIRouter = APIRouter(prefix='/api/v1/service', dependencies=[])

DEFAULT_PAGING_SIZE: int = 25

MAX_PAGE_SIZE: int = 100


@router.get('/data', status_code=200, response_class=ORJSONResponse)
async def get_data(request: Request,
                   list_name: str | None = AssetCache.DEFAULT_ASSET_LIST,
                   member_id: UUID | None = None,
                   first: int = DEFAULT_PAGING_SIZE, after: str | None = None,
                   ingest_status: str | None = None
                   ) -> QueryResponseModel:
    '''
    This API is called by pods. It returns the assets in the requested
    list. In case the request is for all assets of a channel, the
    member_id must be provided as there can be duplicate channel names
    among members of the service.

    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    log_data: dict[str, any] = {
        'remote_addr': request.client.host,
        'api': 'api/v1/service/data',
        'method': 'GET',
        'asset_list': list_name,
        'member_id': member_id,
        'first': first,
        'after': after,
        'ingest_status': ingest_status
    }
    _LOGGER.debug('Data API request received', extra=log_data)

    asset_cache: AssetCache = config.asset_cache

    first = min(first, MAX_PAGE_SIZE)

    filter_name: str | None = None
    if ingest_status:
        filter_name = 'ingest_status'

    if member_id:
        list_name = ChannelCache.get_cursor(member_id, list_name)

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


@router.get('/asset', status_code=200, response_class=ORJSONResponse)
async def get_asset(request: Request, cursor: str | None = None,
                    asset_id: UUID | None = None,
                    member_id: UUID | None = None) -> EdgeResponse:
    '''
    This API is called by pods

    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    log_data: dict[str, any] = {
        'remote_addr': request.client.host,
        'api': 'api/v1/service/asset',
        'method': 'GET',
        'asset_id': asset_id,
        'member_id': member_id
    }
    _LOGGER.debug('Asset API request received', extra=log_data)

    if cursor and (asset_id or member_id):
        raise HTTPException(
            status_code=400,
            detail='Either cursor or asset_id and member_id must be provided'
        )

    if not (cursor or asset_id or member_id):
        raise HTTPException(
            status_code=400,
            detail='Either cursor or asset_id and member_id must be provided'
        )

    asset_cache: AssetCache = config.asset_cache

    if not cursor:
        cursor = asset_cache.get_cursor(member_id, asset_id)

    try:
        edge: EdgeResponse = await asset_cache.get_asset_by_key(cursor)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Asset not found")

    return edge


@router.get('/channel', status_code=200, response_class=ORJSONResponse)
async def get_channel(request: Request, creator: str, member_id: UUID
                      ) -> EdgeResponse[Channel]:
    '''
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    channel_cache: ChannelCache = config.channel_cache

    log_data: dict[str, str] = {
        'remote_addr': request.client.host,
        'member_id': member_id,
        'creator': creator,
        'api': '/api/v1/service/channel',
        'method': 'GET',
    }
    _LOGGER.debug('Channel API received', extra=log_data)

    try:
        edge: EdgeResponse[Channel] | None = await channel_cache.get_channel(
            member_id, creator
        )
    except Exception as exc:
        _LOGGER.exception(f'Failed to get channel: {exc}', extra=log_data)
        raise HTTPException(
            status_code=502, detail='Failed to get channel'
        )

    if not edge:
        raise HTTPException(
            status_code=404, detail=f'Channel {creator} not found'
        )

    return edge


@router.get('/channel/shortcut', status_code=200)
async def get_channel_shortcut(request: Request, shortcut: str
                               ) -> ChannelShortcutResponse:
    '''
    Returns the member_id and creator name for the shortcut

    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    log_data: dict[str, str] = {
        'remote_addr': request.client.host,
        'api': '/api/v1/service/channel/shortcut',
        'method': 'GET',
        'shortcut': shortcut,
    }

    channel_cache: ChannelCache = config.channel_cache

    _LOGGER.debug('Channel shortcut API received', extra=log_data)

    try:
        member_id: UUID
        creator: str
        member_id, creator = await channel_cache.get_shortcut(shortcut)
        log_data['member_id'] = member_id
        log_data['creator'] = creator
    except FileNotFoundError:
        _LOGGER.debug('Shortcut does not exist', extra=log_data)
        raise HTTPException(status_code=404, detail='Unknown channel shortcut')
    except ValueError as exc:
        _LOGGER.debug(
            'Invalid shortcut', extra=log_data | {'exception': str(exc)}
        )
        raise HTTPException(status_code=400, detail='Invalid shortcut')
    except Exception as exc:
        _LOGGER.debug(
            'Shortcut lookup failure', extra=log_data | {'exception': str(exc)}
        )

    if not member_id or not creator:
        _LOGGER.debug('No data found for shortcut', extra=log_data)

    return ChannelShortcutResponse(member_id=member_id, creator=creator)


@router.get('/channel/shortcut_by_value', status_code=200)
def get_channel_shortcut_value(request: Request, member_id: UUID, creator: str
                               ) -> ChannelShortcutValueResponseModel:
    '''
    Returns the value of the shortcut for the given member_id and creator

    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    log_data: dict[str, str] = {
        'remote_addr': request.client.host,
        'api': '/api/v1/service/channel/shortcut',
        'method': 'GET',
        'creator': creator,
        'member_id': 'member_id'
    }

    shortcut: str = ChannelCache.get_shortcut_value(member_id, creator)
    log_data['shortcut'] = shortcut
    _LOGGER.debug('Generate shotcut API request received', extra=log_data)
    return {'shortcut': shortcut}
