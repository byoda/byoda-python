'''
APIs for managing a BYO.Tube-lite account

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

from byotubesvr.database.network_link_store import NetworkLinkStore
from ..models.lite_api_models import NetworkLinkRequestModel
from ..models.lite_api_models import NetworkLinkResponseModel

_LOGGER: Logger = getLogger(__name__)

router = APIRouter(prefix='/api/v1/lite', dependencies=[])

AuthDep = Annotated[LiteRequestAuth, Depends(LiteRequestAuth)]


@router.post('/networklink', response_class=ORJSONResponse)
async def create_network_link(request: Request, link: NetworkLinkRequestModel,
                              auth: AuthDep) -> UUID:
    '''
    Create a new BYO.Tube-lite network link
    '''

    _LOGGER.debug(
        f'Request from {request.client.host} with LiteID: {auth.lite_id}'
    )

    link_store: NetworkLinkStore = config.network_link_store
    try:
        network_link_id: UUID = await link_store.add_link(
            auth.lite_id, link.member_id, link.relation, link.annotations
        )
        if not network_link_id:
            raise HTTPException(409, 'Network link already exists')

        return network_link_id
    except Exception as exc:
        _LOGGER.exception(f'Failed to add network_link: {exc}')
        raise HTTPException(
            status_code=500, detail='Failed to add network_link'
        )


@router.get('/networklinks', response_class=ORJSONResponse)
async def get_network_links(request: Request, auth: AuthDep,
                            member_id: UUID | None = None,
                            relation: str | None = None, first: int = 100,
                            after: UUID | None = None) -> QueryResponseModel:
    '''
    Get all network links for a given LiteID
    '''

    _LOGGER.debug(
        f'Request from {request.client.host} with LiteID: {auth.lite_id}'
    )

    link_store: NetworkLinkStore = config.network_link_store
    try:
        network_links: list[NetworkLinkResponseModel] = \
            await link_store.get_links(
                auth.lite_id, remote_member_id=member_id, relation=relation
            )
    except Exception as exc:
        _LOGGER.exception(f'Failed to get network_links: {exc}')
        raise HTTPException(
            status_code=500, detail='Failed to get network_links'
        )

    if not network_links:
        raise HTTPException(404, 'No network links found')

    after_satisfied: bool = False
    if not after:
        after_satisfied = True

    edges: list[Edge[NetworkLinkResponseModel]] = []
    for link in network_links:
        edge = Edge(
            cursor=str(link.network_link_id), node=link, origin=auth.lite_id
        )
        if after_satisfied is True:
            edges.append(edge)

        if link.network_link_id == after:
            after_satisfied = True

        if len(edges) > first:
            break

    has_next_page: bool = False
    if len(edges) > first:
        has_next_page = True
        edges = edges[:-1]

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


@router.delete('/networklink', response_class=ORJSONResponse)
async def delete_networklink(request: Request, auth: AuthDep,
                             member_id: UUID, relation: str,
                             annotation: str) -> int:
    '''
    Delete a network link for a given LiteID
    '''

    _LOGGER.debug(
        f'Request from {request.client.host} with LiteID: {auth.lite_id}'
    )

    link_store: NetworkLinkStore = config.network_link_store
    result: int = await link_store.remove_creator(
        auth.lite_id, member_id, relation, annotation
    )

    return result
