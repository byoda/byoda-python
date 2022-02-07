'''
/service/search API for the addressbook service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''


import logging
from uuid import UUID
from pydantic import BaseModel

from fastapi import APIRouter, Depends, Request

from byoda.datastore.memberdb import MemberDb

from byoda import config

from ..dependencies.memberrequest_auth import MemberRequestAuthFast

_LOGGER = logging.getLogger(__name__)


class PersonResponseModel(BaseModel):
    given_name: str
    family_name: str
    email: str
    homepage_url: str
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


@router.get('/search/{email}', response_model=PersonResponseModel)
def search(request: Request, email: str,
           auth: MemberRequestAuthFast = Depends(MemberRequestAuthFast)):
    '''
    Submit a Certificate Signing Request for the Member certificate
    and get the cert signed by the Service Members CA
    This API is called by pods
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    member_db: MemberDb = config.server.member_db

    member_id = member_db.kvcache.get(email)
    _LOGGER.debug(
        f'GET Search API called from {request.client.host} for email {email}, '
        f'found {member_id}'
    )

    data = member_db.get_data(UUID(member_id))

    return data
