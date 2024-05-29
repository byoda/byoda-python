'''
Class for modeling content keys

Content keys do not affect the content but are used to
restrict streaming & download access to the content.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import operator

from uuid import UUID
from enum import Enum
from typing import Self
from base64 import b64encode
from logging import getLogger
from datetime import datetime
from datetime import timezone
from datetime import timedelta

from cryptography.hazmat.primitives import hashes

from byoda.datamodel.table import Table
from byoda.datamodel.table import QueryResult

from byoda.datatypes import IdType

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)

DEFAULT_KEY_START_DELAY: int = 86400
DEFAULT_KEY_EXPIRATION_DELAY: int = DEFAULT_KEY_START_DELAY + 86400

RESTRICTED_CONTENT_KEYS_TABLE: str = 'restricted_content_keys'


class ContentKeyStatus(Enum):
    '''
    The different possible statuses for a content key
    '''
    # flake8: noqa=E221
    INACTIVE = 'inactive'
    ACTIVE   = 'active'
    EXPIRED  = 'expired'


class ContentKey:
    '''
    Manage keys in the 'restricted_content_keys' table and/or
    under the /opt/byoda/keys directory
    '''

    __slots__: list[str] = [
        'key', 'key_id', 'not_before', 'not_after', 'table', 'status'
    ]

    def __init__(self, key: str, key_id: int, not_before: datetime,
                 not_after: datetime, table: Table = None) -> None:
        '''
        Instantiate a ContentKey instance

        :param key: the key to sign tokens with
        :param key_id: the id of the key to sign/verify tokens
        :param not_before: what is the earliest date/time that the key can be
        used
        :param not after: what is the latest date/time that the key can be used
        :param table: the table to associate with this key
        '''

        self.key: str = key
        self.key_id: int = int(key_id)
        if isinstance(not_before, str):
            self.not_before = datetime.fromisoformat(not_before)
        else:
            self.not_before: datetime = not_before

        if isinstance(not_after, str):
            self.not_after: datetime = datetime.fromisoformat(not_after)
        else:
            self.not_after: datetime = not_after
        self.table: Table = table

        self.status = ContentKeyStatus.INACTIVE
        now: datetime = datetime.now(tz=timezone.utc)

        _LOGGER.debug(
            f'Checking status of content key starting at {self.not_before}, '
            f'expiring at {self.not_after} '
        )

        if self.not_before > now:
            _LOGGER.debug(f'Key is not yet active: {self.not_before} > {now}')
        else:
            _LOGGER.debug(f'Key might be active, {self.not_before} <= {now}')
            self.status: ContentKeyStatus = ContentKeyStatus.ACTIVE

        if self.not_after > now:
            _LOGGER.debug(f'Key has not yet expired: {self.not_after} > {now}')
        else:
            _LOGGER.debug(f'Key has expired, {self.not_after} <= {now}')
            self.status: ContentKeyStatus = ContentKeyStatus.EXPIRED

    def __lt__(self, other) -> bool:
        '''
        We give precedence to the active key that has become most
        recently 'active'. This allows us to initially create keys
        with really long expiration and once we've confirmed key
        distribution to CDN server is stable, we can start creating
        keys with shorter expiration.
        '''

        if self.status == other.status:
            return self.not_before < other.not_before

        if self.status == ContentKeyStatus.EXPIRED:
            return False
        elif self.status == ContentKeyStatus.INACTIVE:
            return True
        elif self.status == ContentKeyStatus.ACTIVE:
            if other.status == ContentKeyStatus.EXPIRED:
                return False
            else:
                return True
        else:
            raise NotImplementedError(f'Unknown status: {self.status}')

    def as_dict(self) -> dict[str, str | int | datetime | float]:
        '''
        Returns the ContentKey instance as a dict
        '''

        return {
            'key': self.key,
            'key_id': self.key_id,
            'not_before': self.not_before,
            'not_after': self.not_after,
        }

    @staticmethod
    async def create(key: str = None, key_id: int = None, not_before: datetime = None,
               not_after: datetime = None, table: Table = None) -> Self:
        '''
        Creates a new ContentKey instance. This method does not save the
        key to the table. The key_id is automatically generated if the table
        is provided.

        :param key:
        :param key_id: if not key_id is provided, a key_id will be generated
        by taking the highest key_id in the table and adding 1 to it
        :param not_before: what is the earliest date/time that the key can be
        used. If not specified, it defaults to 24 hours after the key is created
        :param not_after: what is the latest date/time that the key can be used.
        If not specified, it defaults to 48 hours after the key is created
        :param table: the table to use for generating the key_id if none is
        provided when this method is invoked
        :returns: ContentKey
        '''

        if key_id is None and not table:
            raise ValueError('key_id must be specified if no table is provided')

        if key_id is None:
            keys: list[ContentKey] = await ContentKey.get_content_keys(table=table)

            keys_sorted_by_key_id: list[ContentKey] = sorted(
                keys, key=operator.attrgetter('key_id'), reverse=True
            )

            if not keys_sorted_by_key_id:
                key_id = 1
            else:
                key_id = keys_sorted_by_key_id[0].key_id + 1

        if not_before is None:
            not_before: datetime = (
                datetime.now(tz=timezone.utc) +
                timedelta(seconds=DEFAULT_KEY_START_DELAY)
            )

        if not_after is None:
            not_after: datetime = (
                datetime.now(tz=timezone.utc) +
                timedelta(DEFAULT_KEY_EXPIRATION_DELAY)
            )

        return ContentKey(key, key_id, not_before, not_after, table)

    @staticmethod
    def from_dict(data: dict[str, str | int | datetime | float]) -> Self:
        '''
        Creates a new ContentKey instance from a dict

        :param data: dict with the following keys: key: str, key_id: int,
        not_before: datetime, not_after: datetime
        :returns: ContentKey
        '''

        return ContentKey(
            data['key'], data['key_id'], data['not_before'], data['not_after']
        )

    async def persist(self, table: Table = None) -> None:
        '''
        Persist the key to the sql table
        '''

        if not table:
            if not self.table:
                raise ValueError(
                    'table must be specified if the key is not already associated '
                    'with a table'
                )

            table = self.table

        required_fields: list[str] = [
            field.name for field in table.columns.values()
            if field.required
        ]
        data: dict[str, object] = self.as_dict()
        cursor: str = Table.get_cursor_hash(data, None, required_fields)

        await table.append(
            self.as_dict(), cursor, origin_id=None, origin_id_type=None,
            origin_class_name=None
        )

    @staticmethod
    async def get_content_keys(table: Table, status: ContentKeyStatus = None
                               ) -> list[Self]:
        '''
        Gets the restricted content keys from the table or file and returns a
        list of ContentKey instances. The returned list is sorted based on
        latest not_before timestamp.

        :param sql_table: an SqlTable instance that must have the fields
        key: str, key_id: int, not_before: datetime, not_after: datetime
        :param filepath: name of a file with an array of items with each
        item having at least the keys: key: str, key_id: int, not_before:
        datetime, not_after: datetime
        :param status: optional ContentKeyStatus to filter the results
        :returns: list of ContentKey instances
        :raises: ValueError if the table is not an ArraySqlTable or does not
        contain the required fields
        '''

        all_key_data: list[QueryResult] = await table.query()

        _LOGGER.debug(
            f'Found {len(all_key_data or ())} keys for restricted content keys in '
            f'SQL table {table.storage_table_name}'
        )

        all_keys: list[ContentKey] = []
        for key_data in all_key_data or []:
            content_key: ContentKey = ContentKey.from_dict(key_data.data)
            all_keys.append(content_key)

        filtered_keys: list[ContentKey] = []
        content_key: ContentKey
        for content_key in all_keys or []:
            if not status or status == content_key.status:
                filtered_keys.append(content_key)

        _LOGGER.debug(
            f'Still got {len(filtered_keys)} keys after filtering for status {status}'
        )

        filtered_keys = sorted(filtered_keys)

        return filtered_keys

    @staticmethod
    async def get_active_content_key(table: Table) -> Self | None:
        '''
        Returns the most recent active content key from the table or file

        :param sql_table: an ArraySqlTable instance that must have the fields
        key: str, key_id: int, not_before: datetime, not_after: datetime
        :param filepath: name of a file with an array of items with each
        item having at least the keys: key: str, key_id: int, not_before:
        datetime, not_after: datetime
        :returns: ContentKey or None
        '''

        active_keys: list[ContentKey] = await ContentKey.get_content_keys(
            table=table, status=ContentKeyStatus.ACTIVE
        )

        if not active_keys:
            return None

        return active_keys[0]

    def generate_token(self, service_id: int, member_id: UUID | str,
                       asset_id: UUID | str,
                       remote_member_id: UUID | None = None,
                       remote_member_idtype: IdType | None = None) -> str:
        '''
        Generates a token for the given service_id and asset_id.

        :returns: a base64-encoded string
        '''

        digest = hashes.Hash(hashes.SHA3_224())
        digest.update(str(service_id).encode('utf-8'))
        digest.update(str(member_id).encode('utf-8'))
        digest.update(str(asset_id).encode('utf-8'))

        # OBSOLETE: once GET /token is removed, remove this if condition
        # and make the remote_member_id and remote_member_idtype parameters
        # required
        if remote_member_id and remote_member_idtype:
            digest.update(str(remote_member_id).encode('utf-8'))
            digest.update(remote_member_idtype.value.encode('utf-8'))

        digest.update(self.key.encode('utf-8'))
        token: bytes = digest.finalize()

        encoded_token: str = b64encode(token).decode('utf-8').replace(' ', '+')
        _LOGGER.debug(
            f'Generated token with service_id {service_id}, member_id: {member_id} '
            f'and asset_id: {asset_id} for remote member '
            f'key_id {self.key_id}: {encoded_token}'
        )
        # TODO: add this line back once GET /token is removed
        #    f'{remote_member_idtype.value} {remote_member_id} for '

        return encoded_token

    def generate_url_query_parameters(self, service_id: int, member_id: UUID | str,
                                      asset_id: UUID | str) -> str:
        '''
        Generates the query parameters for the URL to be used with the CDN

        :param service_id: the service_id
        :param member_id: the member_id
        :param asset_id: the asset_id
        :returns: a string with the query parameters
        :raises: (none)
        '''

        data: str = '&'.join(
            [
                f'service_id={service_id}',
                f'member_id={member_id}',
                f'asset_id={asset_id}',
            ]
        )

        return data
