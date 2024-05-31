'''
CDN App server /content_keys API API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import os

from logging import getLogger
from byoda.datatypes import AuthSource
from datetime import datetime

import orjson

from fastapi import APIRouter, HTTPException
from fastapi import Request

from byoda.models.content_key import ContentKeyRequestModel

from byoda.models.cdn_account_memberships import \
    CdnAccountOriginsRequestModel

from byoda.datatypes import IdType

from byoda.servers.app_server import AppServer

from byoda.util.logger import Logger

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


@router.post('/origins', status_code=201)
async def post_origins(request: Request,
                       origin: CdnAccountOriginsRequestModel,
                       auth: AccountAuthDep) -> None:

    server: AppServer = config.server

    log_extra: dict[str, str] = {
        'remote_addr': request.client.host,
        'service_id': origin.service_id,
        'member_id': origin.member_id
    }

    _LOGGER.debug('Post CDN origins API called', extra=log_extra)

    await auth.authenticate()

    if auth.auth_source != AuthSource.CERT:
        raise HTTPException(
            status_code=403,
            detail='Must authenticate with a certificate'
        )
    if auth.id_type != IdType.ACCOUNT:
        raise HTTPException(
            status_code=403,
            detail='Must authenticate with an account credential'
        )

    log_extra['account_id'] = auth.id

    if not os.path.exists(server.origins_dir):
        os.makedirs(server.origins_dir, exist_ok=True)

    filepath: str = server.paths.CDN_ORIGINS_FILE.format(
        origins_dir=server.origins_dir, service_id=origin.service_id,
        account_id=auth.id
    )
    log_extra['filepath'] = filepath

    origin_data: dict[str, any] = origin.model_dump()
    with open(filepath, 'wb') as file_desc:
        file_desc.write(
            orjson.dumps(
                origin_data, option=orjson.OPT_INDENT_2
            )
        )
    _LOGGER.debug('Persisted origins', extra=log_extra)
