'''
/data API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''


import logging

from fastapi import APIRouter, Depends, Request, HTTPException

# from byoda.datatypes import IdType

from byoda.models import MemberResponseModel

from byoda import config

from ..dependencies.podrequest_auth import PodRequestAuth

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/pod', dependencies=[])


@router.get('/member', response_model=MemberResponseModel)
def get_member(request: Request, service_id: int,
               auth: PodRequestAuth = Depends(PodRequestAuth)):
    '''
    Get metadata for the membership of a service.
    '''

    account = config.server.account

    if service_id not in account.memberships:
        raise HTTPException(
            status_code=404, detail='Not a member of service {service_id}'
        )

    member = account.memberships[service_id]
    return member.as_dict()
