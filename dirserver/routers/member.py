'''
/network/member API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3

The /network/member API is called by pods:
PUT: creates a dns record ${UUID}.member-${SERVICE_ID}.${NETWORK}
DELETE: deletes the dns record

The /service/service POST/DELETE APIs have the same signature but only
informs the service about the availability of the pod.
'''

import logging

from fastapi import APIRouter, Depends, Request, HTTPException


from byoda.datatypes import IdType

from byoda.datamodel.service import Service

from byoda.models.ipaddress import IpAddressResponseModel

from byoda.datastore.dnsdb import DnsDb

from byoda import config

from ..dependencies.memberrequest_auth import MemberRequestAuthFast
from ..dependencies.async_db_session import asyncdb_session

_LOGGER = logging.getLogger(__name__)


router = APIRouter(
    prefix='/api/v1/network',
    dependencies=[]
)


@router.put(
    '/member', response_model=IpAddressResponseModel, status_code=200
)
async def put_member(request: Request, auth: MemberRequestAuthFast = Depends(
                     MemberRequestAuthFast),
                     db_session=Depends(asyncdb_session)):
    '''
    Request DNS record to be hosted for the Common Name of the MemberCert
    '''

    _LOGGER.debug(f'PUT Member API called from {request.client.host}')

    await auth.authenticate()

    # Authorization
    # End of authorization

    if not Service.is_registered(auth.service_id):
        raise HTTPException(
            404, f'Registration for unknown service: {auth.service_id}'
        )

    dnsdb: DnsDb = config.server.network.dnsdb

    await dnsdb.create_update(
        auth.member_id, IdType.MEMBER, auth.remote_addr, db_session,
        service_id=auth.service_id
    )

    _LOGGER.debug(f'Updated DNS record for member {auth.member_id}')
    return {
        'ipv4_address': auth.remote_addr
    }
