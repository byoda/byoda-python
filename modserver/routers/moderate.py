'''
/data API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import logging

from uuid import UUID
from uuid import uuid4
from datetime import datetime
from datetime import timezone

import orjson

from fastapi import APIRouter
from fastapi import Request
from fastapi import HTTPException

from byoda.datatypes import ClaimStatus
from byoda.datatypes import IdType

from byoda.datamodel.app import App
from byoda.datamodel.claim import Claim

from byoda.models.claim_request import ClaimResponseModel
from byoda.models.claim_request import AssetClaimRequestModel

from byoda.datastore.assetdb import AssetDb
from byoda.datastore.memberdb import MemberDb

from byoda.storage.filestorage import FileStorage

from byoda.servers.app_server import AppServer

from byoda import config

from ..dependencies.memberrequest_auth import AuthDep

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/moderate', dependencies=[])


@router.get(
    'member/{member_id}', response_model=ClaimResponseModel
)
async def get_member_moderation(request: Request, member_id: UUID):
    '''
    Get the moderation info of an asset

    :param asset_id: the asset_id of the asset
    :raises: HTTPException 404
    '''

    member_db: MemberDb = config.server.member_db

    _LOGGER.debug(f'GET Moderation API called from {request.client.host}')
    moderation = member_db.get_data(member_id)
    if not moderation:
        return HTTPException(
            status_code=404, detail='No moderation found for asset'
        )
    return moderation.as_dict()


@router.post('/asset',
             response_model=ClaimResponseModel)
async def post_asset_moderation(request: Request,
                                claim_request: AssetClaimRequestModel,
                                auth: AuthDep):
    '''
    Become a member of a service.

    :param claim_data: claim requested for signing
    :raises:
    '''

    _LOGGER.debug(
        f'Post Asset Moderation API called from {request.client.host}'
    )
    await auth.authenticate()

    request_id: UUID = uuid4()
    data = claim_request.model_dump()
    data['request_id'] = str(request_id)
    data['request_timestamp'] = datetime.now(tz=timezone.utc)
    data['requester_id'] = auth.id
    data['requester_type'] = auth.id_type.value
    data['request_status'] = ClaimStatus.PENDING.value

    server: AppServer = config.server
    filepath: str = f'{server.claim_request_dir}/{request_id}.json'
    with open(filepath, 'wb') as claim_file:
        claim_file.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))

    return {
        'claim_status': ClaimStatus.PENDING,
        'claim_signature': None
    }
