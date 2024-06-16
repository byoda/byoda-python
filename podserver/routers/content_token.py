'''
/api/v1/content_auth API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''


from uuid import UUID
from logging import getLogger

from fastapi import APIRouter
from fastapi import Request
from fastapi.exceptions import HTTPException

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.content_key import ContentKey
from byoda.datamodel.table import QueryResult
from byoda.datamodel.content_key import RESTRICTED_CONTENT_KEYS_TABLE
from byoda.datamodel.table import Table
from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.monetization import Monetizations

from byoda.models.content_key import BurstAttestModel
from byoda.models.content_key import ContentTokenRequestModel
from byoda.models.content_key import ContentTokenResponseModel

from byoda.datatypes import IdType

from byoda.datastore.data_store import DataStore

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger

from byoda import config

_LOGGER: Logger = getLogger(__name__)

router = APIRouter(prefix='/api/v1/pod/content', dependencies=[])

# This HTTP header is set by the auth_request processing config of the angie
# server
ORIGNAL_URL_HEADER = 'original-url'

ASSET_CLASS_NAME: str = 'public_assets'

MINIMUM_BURST_POINTS: int = 100


@router.post('/token')
async def post_content_token(
    request: Request, key_request: ContentTokenRequestModel
) -> ContentTokenResponseModel:
    '''
    API to request a token for restricted content
    '''

    service_id: int = key_request.service_id
    asset_id: UUID = key_request.asset_id
    attestation: BurstAttestModel = key_request.attestation
    requesting_member_id: UUID = key_request.member_id
    requesting_member_type: IdType = key_request.member_id_type

    log_extra: dict[str, any] = {
        'service_id': service_id,
        'asset_id': asset_id,
        'remote_addr': request.client.host,
        'data_class': ASSET_CLASS_NAME
    }

    _LOGGER.debug(
        'Received request for content token', extra=log_extra
    )

    server: PodServer = config.server
    account: Account = server.account

    member: Member = await account.get_membership(service_id)
    log_extra['member_id'] = member.member_id
    data_store: DataStore = server.data_store

    _LOGGER.debug('Getting content key table', extra=log_extra)
    key_table: Table = data_store.get_table(
        member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
    )

    table: Table = data_store.get_table(
        member.member_id, ASSET_CLASS_NAME
    )

    data_filter: DataFilterSet = DataFilterSet({'asset_id': {'eq': asset_id}})
    data: list[QueryResult] = await table.query(data_filter)

    if not data or not isinstance(data, list) or not len(data):
        _LOGGER.debug('Asset not found', extra=log_extra)
        raise HTTPException(
            400, f'Token denied for unknown asset_id {asset_id}'
        )

    if len(data) > 1:
        _LOGGER.debug('Found more than one asset', extra=log_extra)

    asset: dict[str, any] = data[0].data

    monetizations: Monetizations = Monetizations.from_dict(
        asset.get('monetizations')
    )
    approve_request: bool
    reason: str
    approve_request, reason = await monetizations.evaluate(
        service_id, requesting_member_id, requesting_member_type,
        attestation, MINIMUM_BURST_POINTS
    )

    if not approve_request:
        _LOGGER.debug(
            'No token because request was not approved',
            extra=log_extra | {'reason': reason}
        )
        raise HTTPException(400, reason)

    key: ContentKey = await ContentKey.get_active_content_key(table=key_table)

    if not key:
        _LOGGER.error('No tokens available', log_extra)
        raise HTTPException(400, 'No tokens available')

    content_token: str = key.generate_token(
        service_id, member.member_id, asset_id,
        remote_member_id=key_request.member_id,
        remote_member_idtype=key_request.member_id_type
    )

    return {
        'key_id': key.key_id,
        'content_token': content_token
    }
