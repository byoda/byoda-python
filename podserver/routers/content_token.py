'''
/api/v1/content_auth API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''


from uuid import UUID
from datetime import UTC
from datetime import datetime
from datetime import timedelta
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
from byoda.datamodel.claim import AppClaim

from byoda.models.content_key import Claim as ClaimModel
from byoda.models.content_key import BurstAttestModel
from byoda.models.content_key import ContentTokenRequestModel
from byoda.models.content_key import ContentTokenResponseModel

from byoda.datatypes import IdType
from byoda.datatypes import MonetizationType

from byoda.datastore.data_store import DataStore

from byoda.secrets.app_data_secret import AppDataSecret

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

# test curls:
# on dev workstation
# curl 'http://localhost/restricted/index.html?service_id=4294929430&member_id=66e41ad6-c295-4843-833c-5e523d34cce1&asset_id=066a050a-03e6-43d5-8d77-9e14fba0ed3b&key_id=1' --header 'Authorization: 1234567890'                            # noqa: E501
#
# against cdn:
# curl -s -v 'https://cdn.byo.host/restricted/restricted.html?service_id=4294929430&key_id=1&asset_id=066a050a-03e6-43d5-8d77-9e14fba0ed3b&member_id=94f23c4b-1721-4ffe-bfed-90f86d07611a' --header 'Authorization: bearer 1234567890'      # noqa: E501

# against pod:
# curl -k -s -v 'https://94f23c4b-1721-4ffe-bfed-90f86d07611a.members-4294929430.byoda.net/restricted/index.html?service_id=4294929430&member_id=66e41ad6-c295-4843-833c-5e523d34cce1&asset_id=066a050a-03e6-43d5-8d77-9e14fba0ed3b&key_id=1' --header 'Authorization: 1234567890'   # noqa: E501


@router.get('/token')
async def content_token(request: Request, service_id: int, asset_id: UUID,
                        signedby: UUID, token: str
                        ) -> ContentTokenResponseModel:
    '''
    API to request a token for restricted content
    '''

    _LOGGER.debug(
        f'Received request for restricted content token, '
        f'service_id={service_id}, asset_id={asset_id}, '
        f'token={token} signed by {signedby} from {request.client.host}'
    )

    if not service_id or not asset_id or not token or not signedby:
        raise HTTPException(
            403, 'Must specify service_id, asset_id, signedby and token'
        )

    server: PodServer = config.server
    account: Account = server.account

    member: Member = await account.get_membership(service_id)

    data_store: DataStore = server.data_store
    key_table: Table = data_store.get_table(
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

    if not key:
        _LOGGER.error('No tokens available')
        raise HTTPException(400, 'No tokens available')

    content_token: str = key.generate_token(
        service_id, member.member_id, asset_id
    )

    return {
        'key_id': key.key_id,
        'content_token': content_token
    }


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

    _LOGGER.debug(
        f'Received request for restricted content token, '
        f'service_id={service_id}, asset_id={asset_id}, '
        f'from {request.client.host}'
    )

    server: PodServer = config.server
    account: Account = server.account

    member: Member = await account.get_membership(service_id)

    data_store: DataStore = server.data_store

    _LOGGER.debug(f'Getting content key table for member {member.member_id}')
    key_table: Table = data_store.get_table(
        member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
    )

    table: Table = data_store.get_table(
        member.member_id, ASSET_CLASS_NAME
    )

    data_filter: DataFilterSet = DataFilterSet({'asset_id': {'eq': asset_id}})
    data: list[QueryResult] = await table.query(data_filter)

    if not data or not isinstance(data, list) or not len(data):
        _LOGGER.debug(
           f'Asset {asset_id} not found in table {ASSET_CLASS_NAME} '
           'for member {member.member_id}'
        )
        raise HTTPException(400, f'Token denied for asset_id {asset_id}')

    if len(data) > 1:
        _LOGGER.debug(f'Found more than one asset with sset_id: {asset_id}')

    asset: dict[str, any] = data[0].data

    approve_request: bool = False
    if ('monetizations' not in asset
            or not isinstance(asset['monetizations'], list)
            or len(asset['monetizations']) == 0):
        approve_request = True
    else:
        for monetization in asset['monetizations']:
            mon_type: str = monetization['monetization_type']
            if mon_type == MonetizationType.FREE.value:
                approve_request = True
                break

            if mon_type == MonetizationType.BURSTPOINTS.value:
                if not attestation:
                    raise HTTPException(
                        400, 'Burst points attestation required'
                    )

                evaluation: bool = await _evaluate_attestation(
                    service_id, requesting_member_id, requesting_member_type,
                    MINIMUM_BURST_POINTS, attestation
                )
                if not evaluation:
                    raise HTTPException(
                        400, 'Burst points attestation invalid'
                    )
                approve_request = True
    if not approve_request:
        raise HTTPException(400, 'Request denied')

    key: ContentKey = await ContentKey.get_active_content_key(table=key_table)

    if not key:
        _LOGGER.error('No tokens available')
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


async def _evaluate_attestation(
        service_id: int, member_id: UUID, member_id_type: IdType,
        min_burst_points: int, attestation: BurstAttestModel) -> bool:
    '''
    Evaluate the attestation to see if the member has sufficient burst points

    :param service_id: the service_id the token is requested for
    :param member_id: the member_id requesting the token
    :param member_id_type: the type of the member_id
    :param min_burst_points: the minimum number of burst points required to
    be attested
    :param attestation: the signed attestation to evaluate
    :return: True if the attestation is valid, False otherwise
    :raises: (none)
    '''

    if attestation.member_id != member_id:
        _LOGGER.debug(
            'Attestation member_id %s does not match requesting member_id %s',
            attestation.member_id, member_id
        )
        return False

    if attestation.member_type != member_id_type:
        _LOGGER.debug(
            'Attestation member_type %s does not match requesting '
            'member_id_type %s',
            attestation.member_type, member_id_type, attestation
        )
        return False

    if attestation.burst_points_greater_equal < min_burst_points:
        _LOGGER.debug(
            'Attestation points %s less than required %s',
            attestation.burst_points_greater_equal, min_burst_points
        )
        return False

    deadline: datetime = datetime.now(tz=UTC) - timedelta(hours=4)
    if attestation.created_timestamp < deadline:
        _LOGGER.debug('Attestation expired: %s', attestation.created_timestamp)
        return False

    if not attestation.claims or len(attestation.claims) == 0:
        _LOGGER.debug('No claims in attestation')
        return False

    claim_model: ClaimModel
    for claim_model in attestation.claims:
        if claim_model.issuer_type != IdType.APP:
            _LOGGER.debug(f'Issuer {claim_model.issuer_id} not an app')
            return False

        claim: AppClaim = AppClaim.from_model(claim_model)
        await claim.get_secret(
            claim.issuer_id, service_id, claim.cert_fingerprint
        )

        burst_points: int = attestation.burst_points_greater_equal
        data: dict[str, any] = {
            'created_timestamp': attestation.created_timestamp,
            'attest_id': attestation.attest_id,
            'service_id': attestation.service_id,
            'member_id': attestation.member_id,
            'member_type': attestation.member_type,
            'burst_points_greater_equal': burst_points,
            'claims': claim_model.claims
        }
        result: bool = claim.verify_signature(data)
        # TODO: Test for revocation of the claim

        if not result:
            _LOGGER.debug('Claim signature invalid')
            return False

        prefix: str = 'burst_points_greater_equal: '
        if (not claim_model.claims
                or not isinstance(claim_model.claims, list)
                or not len(claim_model.claims) == 1
                or not isinstance(claim_model.claims[0], str)
                or not claim_model.claims[0].startswith(prefix)):
            _LOGGER.debug('Invalid claim data: {claim_model.claims}')
            return False

        number_val: str = claim_model.claims[0][len(prefix):]
        try:
            number: int = int(number_val)
            if number < 100:
                _LOGGER.debug('Invalid claim value for burst: {number}')
                return False
        except ValueError:
            _LOGGER.debug('Invalid claim value for burst: {number}')

    return result
