'''
Sample API implementation, for a search API.
Services can chose to either provide REST APIs or GraphQL APIs or both.

This is the REST /service/search API for the addressbook service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''


import logging
from uuid import UUID
from typing import Optional, List
from pydantic import BaseModel

from fastapi import APIRouter, Depends, Request, HTTPException

from byoda.datastore.memberdb import MemberDb
from byoda.models.asset_search import AssetSearchRequestModel
from byoda.models.asset_search import AssetSearchResultsResponseModel

from byoda import config

from ..dependencies.memberrequest_auth import MemberRequestAuthFast

_LOGGER = logging.getLogger(__name__)


class PersonResponseModel(BaseModel):
    given_name: str
    family_name: str
    email: str
    homepage_url: Optional[str]
    avatar_url: Optional[str]
    member_id: UUID

    def __repr__(self):
        return(
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

    member_id = member_db.kvcache.get(email)
    if not member_id:
        raise HTTPException(
            status_code=404, detail=f'No member found for {email}'
        )

    member_id = member_id.decode('utf-8')
    _LOGGER.debug(
        f'GET Search API called from {request.client.host} for email {email}, '
        f'found {member_id}'
    )

    data = member_db.get_data(UUID(member_id))

    data['member_id'] = member_id

    return data


@router.post('/search/asset',
             response_model=List[AssetSearchResultsResponseModel])
async def search_hashtag(request: Request, search: AssetSearchRequestModel,
                         auth: MemberRequestAuthFast = Depends(
                            MemberRequestAuthFast)):
    '''
    Search a member of the service based on the exact match of the
    email address
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    _LOGGER.debug(f'Search API called for assets from {request.client.host}')
    await auth.authenticate()

    # Authorization: not required as called is a member

    member_db: MemberDb = config.server.member_db

    assets: List[AssetSearchResultsResponseModel] = []

    for hashtag in search.hashtags:
        result = member_db.kvcache.get(hashtag)

        member_id = result.member_id.decode('utf-8')
        asset_id = result.asset_id.decode('utf-8')
        _LOGGER.debug(
            f'GET Search API called from {request.client.host} for hashtag '
            f'{hashtag}, found {asset_id}'
        )
        assets.append(
            {

            })
        data = member_db.get_data(UUID(member_id))

        data['member_id'] = member_id

    return data


@router.post('/search/asset/data')
async def asset_data(request: Request, asset_data: AssetSearchRequestModel,
                     auth: MemberRequestAuthFast = Depends(
                            MemberRequestAuthFast)):
    '''
    Submit  it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    _LOGGER.debug(f'Search API called for {hashtag} from {request.client.host}')
    await auth.authenticate()

    # Authorization: not required as caller is a member

    member_db: MemberDb = config.server.member_db

    member_id = member_db.kvcache.get(hashtag)
    if not member_id:
        raise HTTPException(
            status_code=404, detail=f'No member found for {hashtag}'
        )

    member_id = member_id.decode('utf-8')
    _LOGGER.debug(
        f'GET Search API called from {request.client.host} for hashtag {hashtag}, '
        f'found {member_id}'
    )

    data = member_db.get_data(UUID(member_id))

    data['member_id'] = member_id

    return data
