'''
/status API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3

'''

from logging import getLogger
from byoda.util.logger import Logger

from fastapi import APIRouter


_LOGGER: Logger = getLogger(__name__)

router: APIRouter = APIRouter(prefix='/api/v1', dependencies=[])


@router.get('/status')
async def status():
    return {'status': 'healthy'}
