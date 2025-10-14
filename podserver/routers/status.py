'''
/status API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3

'''

from logging import Logger
from logging import getLogger

from fastapi import APIRouter
_LOGGER: Logger = getLogger(__name__)

router: APIRouter = APIRouter(prefix='/api/v1', dependencies=[])


@router.get('/status')
async def status():
    return {'status': 'healthy'}
