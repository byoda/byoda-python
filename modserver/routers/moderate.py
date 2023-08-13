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

from byoda.datamodel.claim import Claim

from byoda.datatypes import IdType
from byoda.datatypes import ClaimStatus

from byoda.models.claim_request import ClaimResponseModel
from byoda.models.claim_request import AssetClaimRequestModel

from byoda.servers.app_server import AppServer

from byoda import config

from ..dependencies.memberrequest_auth import AuthDep

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/moderate', dependencies=[])


@router.post('/asset', response_model=ClaimResponseModel)
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

    asset_id: UUID = claim_request.claim_data.asset_id

    data = claim_request.model_dump()
    data['request_id'] = str(request_id)
    data['request_timestamp'] = datetime.now(tz=timezone.utc)
    data['requester_id'] = auth.id
    data['requester_type'] = auth.id_type.value

    server: AppServer = config.server
    claim_signature: str | None = None
    if os.path.exists(f'{server.whitelist_dir}/{auth.id}'):
        data_fields = sorted(
            claim_request.claim_data.model_dump().keys()
        )
        claim = Claim.build(
            claim_request.claims, server.fqdn, IdType.APP,
            claim_request.claim_data.asset_type, 'asset_id',
            claim_request.claim_data.asset_id,
            data_fields,
            auth.id, auth.id_type,
            f'https://{server.fqdn}/signature',
            f'https://{server.fqdn}/renewal',
            f'https://{server.fqdn}/confirmation'
        )
        claim.create_signature(
            claim_request.claim_data.model_dump(), server.app.data_secret
        )
        claim_signature = claim.signature
        data['request_status'] = ClaimStatus.ACCEPTED.value

        signed_claim_data: dict = claim.as_dict()
        signed_claim_data['claim_data'] = claim_request.claim_data.model_dump()

        with open(f'{server.claim_dir}/{asset_id}', 'w') as claim_file:
            claim_file.write(
                orjson.dumps(
                    signed_claim_data,
                    option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2
                ).decode('utf-8')
            )
    else:
        data['request_status'] = ClaimStatus.PENDING.value

    filepath: str = f'{server.claim_request_dir}/{request_id}.json'
    with open(filepath, 'wb') as claim_file:
        claim_file.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))

        return {
            'status': ClaimStatus(data['request_status']),
            'signature': claim_signature,
            'request_id': request_id,
        }


