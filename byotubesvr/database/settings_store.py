'''
Class for storing asset reactions of BT Lite users

Account and billing related data is stored in byotubesvr.database.sqlstorage
class

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from enum import Enum
from uuid import UUID
from logging import Logger
from logging import getLogger

from fastapi import HTTPException

from .lite_store import LiteStore

_LOGGER: Logger = getLogger(__name__)


SETTINGS_KEY_PREFIX: str = 'lite_settings'


class SettingsType(Enum):
    '''
    Enum for the different types of settings that can be stored
    '''

    ACCOUNT = 'lite_account_settings'
    MEMBER = 'lite_member_settings'


class SettingsStore(LiteStore):
    @staticmethod
    def _get_key(lite_id: UUID, settings_type: SettingsType) -> str:
        '''
        Get the key for the settings

        :param lite_id: UUID of the BT Lite user
        :param settings_type: SettingsType
        :returns: str
        '''

        return f'{SETTINGS_KEY_PREFIX}:{lite_id}:{settings_type.value}'

    async def get_member(self, lite_id: UUID) -> dict[str, any]:
        '''
        Get the account settings for a BT Lite user

        :param lite_id: UUID of the BT Lite user
        :returns: SettingsResponseModel
        :raises: HTTPException
        '''

        key: str = SettingsStore._get_key(lite_id, SettingsType.MEMBER)
        try:
            settings: dict[str, any] | None = await self.client.hgetall(key)
        except Exception as exc:
            _LOGGER.debug(
                'Failed to get settings', extra={'exception': str(exc)}
            )
            raise HTTPException(
                status_code=500, detail='Failed to get settings'
            )

        if not settings:
            raise FileNotFoundError

        return settings

    async def set_member(self, lite_id: UUID,
                         settings: dict[str, str | UUID | bool | int | float]
                         ) -> bool:
        '''
        Set the account settings for a BT Lite user

        :param lite_id: UUID of the BT Lite user
        :param settings: SettingsRequestModel
        :returns: SettingsResponseModel
        :raises: HTTPException
        '''

        log_data: dict[str, any] = settings | {
            'lite_id': lite_id,
        }

        redis_key: str = SettingsStore._get_key(lite_id, SettingsType.MEMBER)
        log_data['key'] = redis_key

        _LOGGER.debug('Setting member settings', extra=log_data)

        existing_data: dict[str, any]
        try:
            existing_data = \
                await self.client.hgetall(redis_key) or {}
        except FileNotFoundError:
            existing_data = {}

        data_changes: bool = False
        data_key: str
        value: str | UUID | bool | int | float
        for data_key, value in settings.items():
            if value is not None:
                if isinstance(value, UUID):
                    value = str(value)
                if isinstance(value, bool):
                    value = int(value)
                # Redis converts all values of hash to a string
                # so that's what we have to compare to
                if existing_data.get(data_key) == str(value):
                    continue
                existing_data[data_key] = value
                data_changes = True

        try:
            await self.client.hmset(redis_key, existing_data)
        except Exception as exc:
            _LOGGER.debug(
                'Failed to set settings', extra={'exception': str(exc)}
            )
            raise HTTPException(
                status_code=500, detail='Failed to set settings'
            )

        return data_changes
