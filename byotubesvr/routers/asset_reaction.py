'''
APIs for managing asset reactions of a BYO.Tube-lite account

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3

'''

from uuid import UUID
from logging import Logger
from logging import getLogger
from typing import Annotated

from fastapi import APIRouter
from fastapi import Request
from fastapi import HTTPException
from fastapi import Depends

from fastapi.responses import ORJSONResponse

from byoda.models.data_api_models import EdgeResponse as Edge
from byoda.models.data_api_models import PageInfoResponse
from byoda.models.data_api_models import QueryResponseModel
from byoda import config

from byotubesvr.auth.request_auth import LiteRequestAuth

from byotubesvr.database.asset_reaction_store import AssetReactionStore
from ..models.lite_api_models import AssetReactionRequestModel
from ..models.lite_api_models import AssetReactionResponseModel

_LOGGER: Logger = getLogger(__name__)

router = APIRouter(prefix='/api/v1/lite', dependencies=[])

AuthDep = Annotated[LiteRequestAuth, Depends(LiteRequestAuth)]


@router.post('/assetreaction', response_class=ORJSONResponse, status_code=201)
async def create_assetreaction(request: Request, auth: AuthDep,
                               reaction: AssetReactionRequestModel,
                               ) -> None:
    '''
    Create a new BYO.Tube-lite account
    '''

    _LOGGER.debug(
        f'Request from {request.client.host} with LiteID: {auth.lite_id}'
    )

    reaction_store: AssetReactionStore = config.asset_reaction_store

    try:
        result: bool = await reaction_store.add_reaction(
            auth.lite_id, reaction
        )
    except Exception as exc:
        _LOGGER.exception(f'Failed to add or update asset_reaction: {exc}')
        raise HTTPException(
            status_code=500, detail='Failed to add or update asset_reaction'
        )


@router.get('/assetreaction', response_class=ORJSONResponse)
async def get_asset_reaction(request: Request, auth: AuthDep, member_id: UUID,
                             asset_id: UUID) -> AssetReactionResponseModel:
    '''
    Get an asset reaction for the lite_id of the account for an asset
    '''

    _LOGGER.debug(
        f'Request from {request.client.host} with LiteID: {auth.lite_id}'
    )

    reaction_store: AssetReactionStore = config.asset_reaction_store

    try:
        asset_reaction: AssetReactionResponseModel = \
            await reaction_store.get_reaction(
                auth.lite_id, member_id, asset_id
            )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='No asset reaction found')
    except Exception as exc:
        _LOGGER.exception(f'Failed to get asset_reaction: {exc}')
        raise HTTPException(
            status_code=500, detail='Failed to get asset reaction'
        )

    return asset_reaction


@router.get('/assetreactions', response_class=ORJSONResponse)
async def get_asset_reactions(
    request: Request, auth: AuthDep,
    first: int = AssetReactionStore.DEFAULT_PAGE_SIZE,
    after: str | None = None
) -> QueryResponseModel:
    '''
    Get all network links for a given LiteID
    '''

    _LOGGER.debug(
        f'Request from {request.client.host} with LiteID: {auth.lite_id}'
    )

    reaction_store: AssetReactionStore = config.asset_reaction_store

    try:
        asset_reactions: list[AssetReactionResponseModel] = \
            await reaction_store.get_reactions(
                auth.lite_id, first, after
            )
    except ValueError:
        raise HTTPException(400, 'Invalid query parameters')
    except Exception as exc:
        _LOGGER.exception(f'Failed to get network_links: {exc}')
        raise HTTPException(
            status_code=500, detail='Failed to get asset reactions'
        )

    if not asset_reactions:
        raise HTTPException(404, 'No asset reactions found')

    asset_reaction: AssetReactionResponseModel
    has_next_page: bool = False
    if len(asset_reactions) > first:
        has_next_page = True
        asset_reactions = asset_reactions[:-1]

    edges: list[Edge[AssetReactionResponseModel]] = []
    for asset_reaction in asset_reactions:
        cursor: str = AssetReactionStore.get_cursor_by_reaction(
            auth.lite_id, asset_reaction
        )
        edge = Edge(
            cursor=cursor, node=asset_reaction, origin=auth.lite_id
        )
        edges.append(edge)

    end_cursor: str = ''
    if len(edges):
        end_cursor = edges[-1].cursor

    response: QueryResponseModel = QueryResponseModel(
        total_count=len(edges), edges=edges,
        page_info=PageInfoResponse(
            has_next_page=has_next_page, end_cursor=end_cursor
        )
    )

    return response


@router.delete('/assetreaction', response_class=ORJSONResponse,
               status_code=204)
async def delete_assetreaction(request: Request, auth: AuthDep,
                               member_id: UUID, asset_id: UUID) -> None:
    '''
    Delete a asset_reaction for the account with the LiteID
    '''

    _LOGGER.debug(
        f'Request from {request.client.host} with LiteID: {auth.lite_id}'
    )

    asset_reaction_store: AssetReactionStore = config.asset_reaction_store

    await asset_reaction_store.delete_reaction(
        auth.lite_id, member_id, asset_id
    )
