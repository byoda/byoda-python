'''
/status API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3

'''

from fastapi import APIRouter

router: APIRouter = APIRouter(prefix='/api/v1', dependencies=[])


@router.get('/status')
async def status() -> dict[str, str]:
    return {'status': 'healthy'}
