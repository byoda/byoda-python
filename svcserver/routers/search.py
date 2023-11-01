'''
Sample API implementation, for a search API.
Services can chose to either provide REST APIs or Data APIs or both.

This is the REST /service/search API for the addressbook service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from uuid import UUID
from logging import getLogger
from byoda.util.logger import Logger

from pydantic import BaseModel

from fastapi import APIRouter, Depends, Request, HTTPException

from byoda.datastore.searchdb import SearchDB, Tracker
from byoda.datastore.memberdb import MemberDb

from byoda.models.asset_search import AssetSubmitRequestModel
from byoda.models.asset_search import AssetSearchRequestModel
from byoda.models.asset_search import AssetSearchResultsResponseModel

from byoda import config

from ..dependencies.memberrequest_auth import MemberRequestAuthFast

_LOGGER: Logger = getLogger(__name__)


class PersonResponseModel(BaseModel):
    given_name: str
    family_name: str
    email: str
    homepage_url: str | None
    avatar_url: str | None
    member_id: UUID

    def __repr__(self):
        return (
            '<PersonResponseModel={given_name: str, family_name: str, '
            'email: str, homepage_url: str, member_id: UUID}>'
        )

    def as_dict(self):
        return {
            'given_name': self.given_name,
            'family_name': self.family_name,
            'email': self.email,
            'homepage_url': self.homepage_url,
            'member_id': self.member_id,
        }


router = APIRouter(
    prefix='/api/v1/service',
    dependencies=[]
)


@router.get('/search/email/{email}', response_model=PersonResponseModel)
async def search_email(request: Request, email: str,
                       auth: MemberRequestAuthFast = Depends(
                           MemberRequestAuthFast)):
    '''
    Search a member of the service based on the exact match of the
    email address
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    _LOGGER.debug(f'Search API called for {email} from {request.client.host}')
    await auth.authenticate()

    # Authorization: not required as called is a member

    member_db: MemberDb = config.server.member_db

    member_id = await member_db.kvcache.get(email)
    if not member_id:
        raise HTTPException(
            status_code=404, detail=f'No member found for {email}'
        )

    member_id = member_id.decode('utf-8')
    _LOGGER.debug(
        f'GET Search API called from {request.client.host} for email {email}, '
        f'found {member_id}'
    )

    data = await member_db.get_data(UUID(member_id))

    data['member_id'] = member_id

    return data


@router.get('/search/asset',
            response_model=list[AssetSearchResultsResponseModel])
async def get_asset(request: Request, search: AssetSearchRequestModel,
                    auth: MemberRequestAuthFast = Depends(
                        MemberRequestAuthFast)):
    '''
    Submit an asset for addiing to the search index
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    _LOGGER.debug(
        'POST Search API called for to submit assets from '
        f'{request.client.host} with hashtags '
        f'{" ".join(search.hashtags or [])} and'
        f'mentions {", ".join(search.mentions or [])}'
    )
    await auth.authenticate()

    # Authorization: not required as caller is a member

    if search.text:
        raise HTTPException(400, 'Fulltext search not implemented')

    search_db: SearchDB = config.server.search_db

    assets: list[AssetSearchResultsResponseModel] = []

    for hashtag in search.hashtags or []:
        results = await search_db.get_list(hashtag, Tracker.HASHTAG)
        for result in results or []:
            data = {'member_id': result[0], 'asset_id': result[1]}
            assets.append(data)

    for mention in search.mentions or []:
        results = await search_db.get_list(mention, Tracker.MENTION)
        for result in results or []:
            data = {'member_id': result[0], 'asset_id': result[1]}
            assets.append(data)

    return assets


@router.post('/search/asset',
             response_model=list[AssetSearchResultsResponseModel])
async def post_asset(request: Request, search: AssetSubmitRequestModel,
                     auth: MemberRequestAuthFast = Depends(
                        MemberRequestAuthFast)):
    '''
    Submit an asset for addiing to the search index
    '''

    _LOGGER.debug(
        'POST Search API called for to submit asset {search.asset_id} from '
        f'{request.client.host} with hashtags '
        f'{", ".join(search.hashtags or [])} '
        f'and mentions {", ".join(search.mentions or [])}'
    )
    await auth.authenticate()

    # Authorization: not required as caller is a member

    search_db: SearchDB = config.server.search_db

    for hashtag in search.hashtags or []:
        await search_db.create_append(
            hashtag, auth.member_id, search.asset_id, Tracker.HASHTAG
        )

    for mention in search.mentions or []:
        await search_db.create_append(
            mention, auth.member_id, search.asset_id, Tracker.MENTION
        )

    return [
        {
            'member_id': auth.member_id,
            'asset_id': search.asset_id,
        }
    ]


@router.delete('/search/asset',
               response_model=list[AssetSearchResultsResponseModel])
async def delete_asset(request: Request, search: AssetSubmitRequestModel,
                       auth: MemberRequestAuthFast = Depends(
                           MemberRequestAuthFast)):
    '''
    Submit an asset for addiing to the search index
    '''

    _LOGGER.debug(
        f'DELETE Search API called to remove asset {search.asset_id} from '
        f'host {request.client.host}'
    )
    await auth.authenticate()

    # Authorization: not required as caller is a member

    search_db: SearchDB = config.server.search_db

    for hashtag in search.hashtags or []:
        await search_db.erase_from_list(
            hashtag, auth.member_id, search.asset_id, Tracker.HASHTAG
        )

    for mention in search.mentions or []:
        await search_db.erase_from_list(
            mention, auth.member_id, search.asset_id, Tracker.MENTION
        )

    return [
        {
            'member_id': auth.member_id,
            'asset_id': search.asset_id,
        }
    ]
