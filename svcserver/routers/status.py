'''
/status API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3

'''

import logging

from fastapi import APIRouter


_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1', dependencies=[])


@router.get('/status')
async def status():
    return {'status': 'healthy'}
