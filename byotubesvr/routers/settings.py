'''
APIs for managing the settings for a BYO.Tube-lite account

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3

'''

from logging import Logger
from logging import getLogger
from typing import Annotated

from fastapi import APIRouter
from fastapi import Request
from fastapi import HTTPException
from fastapi import Depends

from fastapi.responses import ORJSONResponse

from byotubesvr.models.lite_api_models import SettingsRequestModel
from byotubesvr.models.lite_api_models import SettingsResponseModel

from byoda import config

from byotubesvr.auth.request_auth import LiteRequestAuth

from byotubesvr.database.settings_store import SettingsType
from byotubesvr.database.settings_store import SettingsStore

_LOGGER: Logger = getLogger(__name__)

router = APIRouter(prefix='/api/v1/lite', dependencies=[])

AuthDep = Annotated[LiteRequestAuth, Depends(LiteRequestAuth)]


@router.get('/settings/member', response_class=ORJSONResponse)
async def get_member_settings(request: Request, auth: AuthDep
                              ) -> SettingsResponseModel:
    '''
    Create a new BYO.Tube-lite network link
    '''

    log_data: dict[str, any] = {
        'method': 'GET',
        'API': 'settings/member',
        'remote_addr': request.client.host,
        'lite_id': auth.lite_id,
    }

    _LOGGER.debug('GET settings request received', extra=log_data)

    settings_store: SettingsStore = config.settings_store

    try:
        settings: dict[str, str] = await settings_store.get_member(
            auth.lite_id
        )
        if not settings:
            raise HTTPException(status_code=404, detail='Settings not found')

        return settings
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail='No settings found for this user'
        )
    except Exception as exc:
        _LOGGER.debug(
            'Could not get settings', extra=log_data | {'exception': str(exc)}
        )
        raise HTTPException(status_code=500, detail='Failed to get settings')


@router.patch('/settings/member', response_class=ORJSONResponse)
async def set_member_settings(request: Request, auth: AuthDep,
                              settings: SettingsRequestModel) -> bool:
    '''
    Create a new BYO.Tube-lite network link

    :returns: bool, True if any existing setting was changed
    '''

    settings_store: SettingsStore = config.settings_store

    log_data: dict[str, any] = {
        'method': 'PATCH',
        'API': 'settings/member',
        'remote_addr': request.client.host,
        'lite_id': auth.lite_id,
        'settings_type': SettingsType.MEMBER,
        'nick': settings.nick,
        'show_external_assets': settings.show_external_assets,
    }

    _LOGGER.debug('Request received', extra=log_data)

    try:
        changes: bool = await settings_store.set_member(
            auth.lite_id, settings.model_dump()
        )
    except Exception as exc:
        _LOGGER.debug(
            'Could not set settings', extra=log_data | {'exception': str(exc)}
        )
        raise HTTPException(
            status_code=500, detail='Failed to set settings'
        )

    return changes
