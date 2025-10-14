'''
customer APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import base64

from datetime import UTC
from datetime import datetime
from logging import Logger
from logging import getLogger

from fastapi import Request
from fastapi import APIRouter
from fastapi import HTTPException

_LOGGER: Logger = getLogger(__name__)

router: APIRouter = APIRouter(prefix='/api/v1/service/support', dependencies=[])

LISTS: list[str] = ['creator-announcements']
EMAIL_SALT: str = 'byotube'
SUBSCRIPTIONS_FILE: str = '/var/tmp/subscriptions.csv'


@router.get('/subscribe', status_code=200)
async def subscribe(request: Request, email: str, listname: str) -> str:
    if listname not in LISTS:
        raise HTTPException(
            status_code=404, detail=f'Unknown mailing list {listname}'
        )

    log_data: dict[str, str] = {
        'email': email,
        'listname': listname,
        'remote_addr': request.client.host
    }

    _LOGGER.debug('Received mailing list subscribe request', extra=log_data)
    with open(SUBSCRIPTIONS_FILE, 'a') as file_desc:
        line: str = (
            f'subscribe,{datetime.now(tz=UTC).isoformat()},{listname},{email}'
            '\n'
        )
        file_desc.write(line)

    return (
        f'You have subscribed to list {listname} '
        f'with email address {email}'
    )


@router.get('/unsubscribe', status_code=200)
async def unsubscribe(request: Request, data: str, listname: str) -> str:
    _LOGGER.debug(f'Unsubscribe request from {request.client.host}')
    decoded: str = base64.urlsafe_b64decode(data).decode('utf-8')
    if not decoded.startswith(f'{EMAIL_SALT}:'):
        raise HTTPException(
            status_code=400, detail='Invalid email address in data'
        )
    if listname not in LISTS:
        raise HTTPException(
            status_code=404, detail=f'Unknown mailing list {listname}'
        )

    email: str = decoded[len(EMAIL_SALT) + 1:]

    log_data: dict[str, str] = {
        'email': email,
        'listname': listname,
        'remote_addr': request.client.host
    }

    _LOGGER.debug('Received mailing list unsubscribe request', extra=log_data)

    with open(SUBSCRIPTIONS_FILE, 'a') as file_desc:
        line: str = (
            f'unsubscribe,{datetime.now(tz=UTC).isoformat()},{listname},{email}'
            '\n'
        )
        file_desc.write(line)

    return (
        f'You have unsubscribed email address {email} from list {listname}'
    )
