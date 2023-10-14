'''
/data API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os

from uuid import UUID
from uuid import uuid4
from logging import getLogger
from byoda.util.logger import Logger
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

_LOGGER: Logger = getLogger(__name__)

router: APIRouter = APIRouter(prefix='/api/v1/moderate', dependencies=[])


@router.post('/asset', response_model=ClaimResponseModel)
async def post_asset_moderation(request: Request,
                                claim_request: AssetClaimRequestModel,
                                auth: AuthDep):
    '''
    Request moderation of an asset

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

    whitelisted: bool = False
    if os.path.exists(f'{server.whitelist_dir}/{auth.id}'):
        _LOGGER.debug(f'Whitelisted moderation request for member {auth.id}')
        whitelisted = True
    elif (claim_request.claim_data.publisher == 'YouTube'
            and claim_request.claim_data.publisher_asset_id):
        _LOGGER.debug(
            'Whitelisting moderation request for YouTube video'
            f'{claim_request.claim_data.publisher_asset_id}'
        )
        whitelisted = True

    claim_signature: str | None = None
    if whitelisted:
        data_fields = sorted(
            claim_request.claim_data.model_dump().keys()
        )

        claim = Claim.build(
            claim_request.claims, server.app_id, IdType.APP,
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
        data['status'] = ClaimStatus.ACCEPTED.value

        signed_claim_data: dict = claim.as_dict()
        signed_claim_data['claim_data'] = claim_request.claim_data.model_dump()

        accepted_claim_file: str = server.get_claim_filepath(
            ClaimStatus.ACCEPTED, asset_id
        )
        _LOGGER.debug(f'Writing accepted claim to {accepted_claim_file}')
        with open(accepted_claim_file, 'w') as claim_file:
            claim_file.write(
                orjson.dumps(
                    signed_claim_data,
                    option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2
                ).decode('utf-8')
            )

        status: ClaimStatus = ClaimStatus(data['status'])
        cert_fingerprint: str = claim.cert_fingerprint
        cert_expiration = claim.cert_expiration
        signature_timestamp: datetime = claim.signature_timestamp
    else:
        data['status'] = ClaimStatus.PENDING.value
        request_file = server.get_claim_filepath(
            ClaimStatus.PENDING, request_id
        )
        with open(request_file, 'wb') as claim_file:
            claim_file.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))

        status: ClaimStatus = ClaimStatus.PENDING
        cert_fingerprint: str | None = None
        cert_expiration: datetime | None = None
        claim_signature: str | None = None
        signature_timestamp: datetime | None = None

    return {
        'status': status,
        'request_id': request_id,
        'requester_id': auth.id,
        'requester_type': auth.id_type,
        'issuer_id': server.app.data_secret.app_id,
        'issuer_type': IdType.APP,
        'cert_fingerprint': cert_fingerprint,
        'cert_expiration': cert_expiration,
        'signature': claim_signature,
        'signature_timestamp': signature_timestamp,
    }
