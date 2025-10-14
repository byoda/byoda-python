'''
API search APIs for both addressbook and byo.tube

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2024
:license    : GPLv3
'''

from logging import Logger
from logging import getLogger

from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import ORJSONResponse

from byoda.datacache.asset_cache import AssetCache

from byoda.models.data_api_models import EdgeResponse as Edge

from byoda import config

_LOGGER: Logger = getLogger(__name__)

router = APIRouter(prefix='/api/v1/service', dependencies=[])


@router.get('/search/asset', response_class=ORJSONResponse)
async def get_asset(request: Request, text: str, offset: int = 0,
                    num: int = 10) -> list[Edge]:
    '''
    Submit an asset for adding to the search index
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    _LOGGER.debug(
        f'GET Search API called for from {request.client.host} with search '
        f'parameter {text}'
    )

    asset_cache: AssetCache = config.asset_cache

    assets: list[Edge] = await asset_cache.search(text, offset, num)

    return assets
