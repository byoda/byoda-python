'''
/api/v1/content_auth API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from uuid import UUID
from logging import getLogger

from fastapi import APIRouter, Request
from fastapi.exceptions import HTTPException

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.content_key import ContentKey
from byoda.datamodel.content_key import ContentKeyStatus
from byoda.datamodel.content_key import RESTRICTED_CONTENT_KEYS_TABLE
from byoda.datamodel.table import Table

from byoda.models.content_key import ContentKeyResponseModel

from byoda.datastore.data_store import DataStore

from byoda.servers.pod_server import PodServer

from byoda import config

_LOGGER = getLogger(__name__)

router = APIRouter(prefix='/api/v1/pod/content', dependencies=[])

# This HTTP header is set by the auth_request processing config of the nginx
# server
ORIGNAL_URL_HEADER = 'original-url'

# test curls:
# on dev workstation
# curl 'http://localhost/restricted/index.html?service_id=4294929430&member_id=66e41ad6-c295-4843-833c-5e523d34cce1&asset_id=066a050a-03e6-43d5-8d77-9e14fba0ed3b&key_id=1' --header 'Authorization: 1234567890'                            # noqa: E501
#
# against cdn:
# curl -s -v 'https://cdn.byoda.io/restricted/restricted.html?service_id=4294929430&key_id=1&asset_id=066a050a-03e6-43d5-8d77-9e14fba0ed3b&member_id=94f23c4b-1721-4ffe-bfed-90f86d07611a' --header 'Authorization: bearer 1234567890'      # noqa: E501

# against pod:
# curl -k -s -v 'https://94f23c4b-1721-4ffe-bfed-90f86d07611a.members-4294929430.byoda.net/restricted/restricted.html'                                                                                                                      # noqa: E501


@router.get('/asset')
async def get_asset(request: Request, service_id: int = None,
                    member_id: UUID = None, asset_id: UUID = None):

    '''
    This is an internal API called by a sub-request in nginx. It is
    not accessible externally
    '''

    token: str = request.headers.get('Authorization')
    key_id: str = request.headers.get('X-Authorizationkeyid')

    _LOGGER.debug(
        f'Received request for token check, service_id={service_id}, '
        f'member_id={member_id}, asset_id={asset_id}, '
        f'key_id={key_id}, token={token}'
    )

    if not service_id or not member_id or not asset_id:
        _LOGGER.debug('Missing query parameters')
        raise HTTPException(
            403, 'Must specify service_id, member_id, asset_id, and key_id'
        )

    if key_id is None:
        _LOGGER.debug('No Key ID provided in X-Authorizationkeyid header')
        raise HTTPException(403, 'No key_id provided')

    try:
        key_id = int(key_id)
    except ValueError:
        _LOGGER.debug(
            f'Key ID {key_id} provided in X-Authorizationkeyid header is '
            'not an integer'
        )
        raise HTTPException(403, 'key_id is not an integer')

    if not token:
        _LOGGER.debug('No token provided in Authorization header')
        raise HTTPException(403, 'No token provided')

    if token.startswith('Bearer ') or token.startswith('bearer '):
        token = token[7:]
        _LOGGER.debug(f'Extracted token: {token}')

    server: PodServer = config.server
    account: Account = server.account
    await account.load_memberships()

    member: Member = account.memberships.get(service_id)
    if member_id != member.member_id:
        _LOGGER.debug('Invalid member ID')
        raise HTTPException(403, 'Invalid member_id: {member_id}')

    data_store: DataStore = server.data_store
    key_table: Table = data_store.get_table(
        member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
    )

    keys = await ContentKey.get_content_keys(
        table=key_table, status=ContentKeyStatus.ACTIVE
    )

    if not keys:
        _LOGGER.debug('No active keys found')
        raise HTTPException(400, f'No keys found for member {member_id}')

    keys_dict = {key.key_id: key for key in keys}

    key: ContentKey = keys_dict.get(key_id)
    if not key:
        _LOGGER.debug(f'Key_id {key_id} specified in request does not exist')
        raise HTTPException(403, 'Invalid key_id')

    generated_token = key.generate_token(service_id, member_id, asset_id)
    _LOGGER.debug(f'Looking for match with token: {generated_token}')

    if generated_token != token:
        _LOGGER.debug(f'Token mismatch: {token} != {generated_token}')
        raise HTTPException(403, 'Invalid token')

    return None


@router.get('/token')
async def content_token(request: Request, service_id: int, asset_id: UUID,
                        signedby: UUID, token: str) -> ContentKeyResponseModel:
    '''
    API to request a token for restricted content
    '''

    _LOGGER.debug(
        f'Received request for restricted content token, '
        f'service_id={service_id},  asset_id={asset_id}, '
        f'token={token} signed by {signedby} from {request.client.host}'
    )

    if not service_id or not asset_id or not token or not signedby:
        raise HTTPException(
            403, 'Must specify service_id, asset_id, signedby and token'
        )

    server: PodServer = config.server

    account: Account = server.account
    await account.load_memberships()
    member: Member = account.memberships.get(service_id)

    data_store: DataStore = server.data_store
    key_table = data_store.get_table(
        member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
    )

    # SECURITY: Enable this if/when request is authenticated using pod-specific
    # JWT
    # We may not have to enable this as restricted content keys are only used
    # to make it harder to access content by someone that is not meant to have
    # access. Right now, someone needs to know the asset_id, which is
    # impossible to guess.
    # table: Table = data_store.get_table(
    #    member.member_id, class_name
    # )
    # data = table.query({'asset_id': asset_id})
    #
    # if not len(data):
    #    _LOGGER.debug(
    #        f'Asset {asset_id} not found in table {class_name} '
    #        'for member {member.member_id}'
    #    )
    #    raise HTTPException(400, f'Token denied for asset_id {asset_id}')

    key: ContentKey = await ContentKey.get_active_content_key(table=key_table)

    content_token = key.generate_token(service_id, member.member_id, asset_id)

    return {
        'key_id': key.key_id,
        'content_token': content_token
    }
