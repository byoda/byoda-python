'''
/data API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os

from uuid import UUID
from logging import getLogger
from byoda.util.logger import Logger
from datetime import datetime

import orjson

from fastapi import APIRouter
from fastapi import Request

from byoda.models.content_key import ContentKeyRequestModel

from byoda.servers.app_server import AppServer

from byoda import config

from ..dependencies.memberrequest_auth import AuthDep

_LOGGER: Logger = getLogger(__name__)

router: APIRouter = APIRouter(prefix='/api/v1/cdn', dependencies=[])


@router.post('/content_keys')
async def post_content_keys(request: Request,
                            content_keys: list[ContentKeyRequestModel],
                            auth: AuthDep) -> None:
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
