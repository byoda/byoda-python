'''
CDN App server /content_keys API API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os

from logging import getLogger
from byoda.datatypes import AuthSource
from byoda.util.logger import Logger
from datetime import datetime

import orjson

from fastapi import APIRouter, HTTPException
from fastapi import Request

from byoda.models.content_key import ContentKeyRequestModel
from byoda.models.cdn_account_memberships import \
    CdnAccountMembershipsRequestModel

from byoda.servers.app_server import AppServer

from byoda import config

from ..dependencies.memberrequest_auth import AuthDep as MemberAuthDep
from ..dependencies.accountrequest_auth import AuthDep as AccountAuthDep

_LOGGER: Logger = getLogger(__name__)

router: APIRouter = APIRouter(prefix='/api/v1/cdn', dependencies=[])


@router.post('/content_keys')
async def post_content_keys(request: Request,
                            content_keys: list[ContentKeyRequestModel],
                            auth: MemberAuthDep) -> None:
    '''
    Submit content keys used to generate content tokens for
    content to which access is restricted

    :param content_keys: the complete list of keys that the member
    may use to create content tokens.
    :raises:
    '''

    server: AppServer = config.server

    _LOGGER.debug(
        f'Post CDN content keys API called from {request.client.host}'
    )
    await auth.authenticate()

    _LOGGER.debug(
        f'Post CDN content keys API called by member {auth.id} with '
        f'{len(content_keys)} keys'
    )

    if not os.path.exists(server.keys_dir):
        os.makedirs(server.keys_dir, exist_ok=True)

    filepath: str = os.path.join(server.keys_dir, f'{auth.id}-keys.json')
    file_data: list[dict[str, str | int | datetime]] = [
        key.as_dict() for key in content_keys
    ]

    with open(filepath, 'wb') as file_desc:
        file_desc.write(
            orjson.dumps(
                file_data, option=orjson.OPT_INDENT_2
            )
        )
    _LOGGER.debug(f'Wrote {len(content_keys)} keys to {filepath}')


@router.post('/memberships')
async def post_memberships(request: Request,
                           membership_ids: CdnAccountMembershipsRequestModel,
                           auth: AccountAuthDep) -> None:
    '''
    Submit list for memberships for an account. This API must be authenticated
    using an account TLS secret

    :param membership_ids: The memberships for an account
    :returns: (none)
    :raises:
    '''

    server: AppServer = config.server

    _LOGGER.debug(
        f'Post CDN account memberships API called from {request.client.host}'
    )
    await auth.authenticate()

    _LOGGER.debug(
        f'Post CDN account memberships API called  {auth.id} with '
        f'{len(membership_ids.membership_ids)} keys'
    )

    if auth.auth_source != AuthSource.ACCOUNT:
        raise HTTPException(
            status_code=403,
            detail='Must authenticate with a credential for an account'
        )

    if auth.id != membership_ids.account_id:
        raise HTTPException(
            status_code=403,
            detail='Specified Account ID does not match authentication account'
        )
