'''
/data API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''


import logging

from fastapi import APIRouter, Request, HTTPException

from byoda.datamodel.member import Member

from byoda.models import AuthTokenResponseModel

from byoda import config

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/pod', dependencies=[])


@router.get(
    '/authtoken/service_id/{service_id}',
    response_model=AuthTokenResponseModel
)
def get_member_authtoken(request: Request, service_id: int):
    '''
    Get an authentication token for the membership

    This API must be secured by a reverse proxy!

    :param service_id: service_id of the service
    :raises: HTTPException 404
    '''

    account = config.server.account

    # Make sure we have the latest updates of memberships
    account.load_memberships()

    member: Member = account.memberships.get(service_id)

    if not member:
        raise HTTPException(
            status_code=404,
            detail='Not a member of service with ID {service_id}'
        )

    jwt = member.create_jwt()
    return jwt.as_dict()
