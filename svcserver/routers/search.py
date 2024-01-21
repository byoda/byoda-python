'''
API search APIs for both addressbook and byo.tube

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from uuid import UUID
from logging import getLogger
from byoda.util.logger import Logger

from pydantic import BaseModel

from fastapi import APIRouter, Depends, Request, HTTPException

from byoda.datacache.asset_cache import AssetCache

from byoda.models.data_api_models import EdgeResponse as Edge

from byoda.datastore.memberdb import MemberDb

from byoda.servers.service_server import ServiceServer

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

    def as_dict(self) -> dict[str, any]:
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

    data: dict = await member_db.get_data(UUID(member_id))

    data['member_id'] = member_id

    return data


@router.get('/search/asset',
            response_model=list[Edge])
async def get_asset(request: Request, text: str, offset: int = 0,
                    num: int = 10):
    '''
    Submit an asset for adding to the search index
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    _LOGGER.debug(
        f'GET Search API called for from {request.client.host} with search '
        f'parameter {text}'
    )

    server: ServiceServer = config.server
    asset_cache: AssetCache = server.asset_cache

    assets: list[Edge] = await asset_cache.search(text, offset, num)

    return assets
