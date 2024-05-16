'''
Class for storing asset reactions of BT Lite users

Account and billing related data is stored in byotubesvr.database.sqlstorage
class

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from uuid import UUID
from datetime import UTC
from datetime import datetime
from logging import getLogger

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from byoda.util.logger import Logger

from byotubesvr.models.lite_api_models import AssetReactionRequestModel
from byotubesvr.models.lite_api_models import AssetReactionResponseModel


from .lite_store import LiteStore

_LOGGER: Logger = getLogger(__name__)


ASSET_REACTIONS_KEY_PREFIX = 'asset_reactions'


class AssetReactionStore(LiteStore):
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 3 * DEFAULT_PAGE_SIZE

    async def get_reaction(self, lite_id: UUID, member_id: UUID, asset_id: UUID
                           ) -> AssetReactionResponseModel | None:
        '''
        Get an asset reaction for a user
        '''

        AssetReactionStore._check_parameters(lite_id, member_id, asset_id)

        reaction_key: str
        _: str
        reaction_key, _ = AssetReactionStore._get_keys(
            lite_id, member_id, asset_id
        )

        data: dict[str, any] = await self.client.json().get(reaction_key)

        if data is None:
            raise FileNotFoundError

        _LOGGER.debug(
            f'Found a reaction for lite_id {lite_id}, '
            f'member_id {member_id}, asset_id {asset_id}'
        )

        return AssetReactionResponseModel(**data)

    async def get_reactions(self, lite_id: UUID,
                            first: int = DEFAULT_PAGE_SIZE,
                            after: str | None = None
                            ) -> list[AssetReactionResponseModel]:
        '''
        Get all asset reactions for a user

        :param lite_id: UUID of the lite account that is requesting the
        reactions
        :param first: the number of reactions to return
        :param after: the cursor to start after
        :returns: The response to the query with AssetReactionResponseModel as
        node type. The length of the list returned will be one more than the
        requested number of items if there are more items available to be
        returned
        :raises: ValueError if the value of the after parameter is not a valid
        cursor
        '''

        if not isinstance(lite_id, UUID):
            lite_id = UUID(lite_id)

        if not isinstance(first, int):
            raise ValueError(f'Invalid number of items requested: {first}')

        if first > AssetReactionStore.MAX_PAGE_SIZE:
            raise ValueError(
                f'Max page size is {AssetReactionStore.MAX_PAGE_SIZE}'
            )

        if first < 1:
            raise ValueError('Invalid number of items requested')

        if after:
            AssetReactionStore._validate_reaction_key(lite_id, after)

        _: str
        sorted_set_key: str
        _, sorted_set_key = AssetReactionStore._get_keys(lite_id)

        # Get more reactions than requested to account for the possibility that
        # asset_reactions have been deleted without the sorted set being
        # updated
        step: int = first * 2

        cursor_found: bool = True
        if after:
            cursor_found = False

        # Start of the range of the sorted set for
        start_index: int = 0

        results: list[AssetReactionResponseModel] = []
        while True:
            removals: list[str] = []
            cursors: list[str] = await self.client.zrevrange(
                sorted_set_key,
                start_index,
                start_index + step - 1
            )
            for cursor in cursors:
                if not cursor_found and cursor == after:
                    cursor_found = True
                    continue

                if cursor_found:
                    data: dict[str, str] = await self.client.json().get(cursor)
                    if data:
                        results.append(data)
                    else:
                        removals.append(cursor)

                    if len(results) == first + 1:
                        break

            # Delete items in the sorted set for which the key was not found
            if removals:
                await self.client.zrem(sorted_set_key, *removals)
                # Next time we request the next set of cursors, we need to
                # adjust the start index by the number elements removed
                start_index -= len(removals)
                removals = []

            # We are at the end of the sorted set if we got less reactions
            # than we requested
            if len(cursors) < step:
                break

            if len(results) == first + 1:
                break

            start_index += step

        return [AssetReactionResponseModel(**item) for item in results or []]

    async def add_reaction(self, lite_id: UUID,
                           asset_reaction: AssetReactionRequestModel) -> bool:
        '''
        Add an asset reaction for a user

        :param lite_id: UUID of the lite account that is creating the reaction
        :param asset_reaction: AssetReactionRequestModel of the reaction
        :returns: True if the reaction was added, False if an existing
        reaction was
        updated
        '''

        if not isinstance(lite_id, UUID):
            lite_id = UUID(lite_id)

        member_id: UUID = asset_reaction.member_id
        asset_id: UUID = asset_reaction.asset_id

        reaction_key: str
        sorted_set_key: str
        reaction_key, sorted_set_key = AssetReactionStore._get_keys(
            lite_id, member_id, asset_id
        )

        existing_reaction: AssetReactionResponseModel | None
        try:
            existing_reaction = await self.get_reaction(
                lite_id, member_id, asset_id
            )
        except FileNotFoundError:
            existing_reaction = None

        data: dict[str, any]
        if existing_reaction is None:
            if not asset_reaction.asset_url:
                raise ValueError('asset_url is required for a new reaction')
            if not asset_reaction.asset_class:
                raise ValueError('asset_url is required for a new reaction')

            data = asset_reaction.model_dump()
        else:
            if (asset_reaction.asset_url and
                    asset_reaction.asset_url != existing_reaction.asset_url):
                raise ValueError('asset_url cannot be changed')

            if (asset_reaction.asset_class and
                    asset_reaction.asset_class !=
                    existing_reaction.asset_class):
                raise ValueError('asset_class cannot be changed')

            if asset_reaction.relation is not None:
                existing_reaction.relation = asset_reaction.relation

            if asset_reaction.bookmark is not None:
                existing_reaction.bookmark = asset_reaction.bookmark

            # You can remove an asset from a list by setting list_name to ''
            if asset_reaction.list_name == '':
                existing_reaction.list_name = None
            elif asset_reaction.list_name is not None:
                existing_reaction.list_name = asset_reaction.list_name

            # When we update an existing reaction, we update its
            # created_timestamp. This field is used to calculate the 'score'
            # of the Redis sorted set. So we need to remove the original
            # entry to the sorted set and add the updated entry
            await self.client.zrem(sorted_set_key, reaction_key)

            data = existing_reaction.model_dump()

        data['created_timestamp'] = datetime.now(tz=UTC).timestamp()
        # We need to create a new reaction and add it to the sorted set
        await self.client.zadd(
            sorted_set_key, {reaction_key: data['created_timestamp']}
        )

        jsonable_data: dict[str, any] = jsonable_encoder(data)

        await self.client.json().set(reaction_key, '$', jsonable_data)

        return not bool(existing_reaction)

    async def delete_reaction(self, lite_id, member_id: UUID, asset_id: UUID
                              ) -> None:
        '''
        Delete an asset reaction for an asset
        '''

        AssetReactionStore._check_parameters(lite_id, member_id, asset_id)

        reaction_key: str
        sorted_set_key: str
        reaction_key, sorted_set_key = AssetReactionStore._get_keys(
            lite_id, member_id, asset_id
        )

        result: int = await self.client.zrem(sorted_set_key, reaction_key)
        reactions_count: int = await self.client.delete(reaction_key)
        if not reactions_count and not result:
            raise HTTPException(404, 'No asset reaction found')

    @staticmethod
    def _get_keys(lite_id: UUID, member_id: UUID | None = None,
                  asset_id: UUID | None = None) -> tuple[str, str]:
        '''
        Gets the keys for the asset reaction and for the sorted set of all
        reactions
        by the lite_id account

        :param lite_id: UUID of the lite account that is creating the reaction
        :param member_id: UUID of the member who published the asset
        :param asset_id: UUID of the asset that the reaction is for
        :returns: tuple of the asset reaction key and the key of the Redis
        ordered set storing all the reactions by the account with the lite_id.
        If member_id and asset_id are both none then the asset reaction key
        will be set to None
        raises: ValueError
        '''

        AssetReactionStore._check_parameters(lite_id, member_id, asset_id)

        if bool(member_id) != bool(asset_id):
            raise ValueError(
                'Both member_id and asset_id or neither must be set'
            )

        reaction_key: str = None
        if member_id and asset_id:
            reaction_key: str = AssetReactionStore._get_cursor(
                lite_id, member_id, asset_id
            )

        sorted_set_key: str = \
            f'{ASSET_REACTIONS_KEY_PREFIX}-sortedset:{lite_id}'

        return (reaction_key, sorted_set_key)

    @staticmethod
    def get_cursor_by_reaction(lite_id: UUID,
                               asset_reaction: AssetReactionResponseModel
                               ) -> str:
        '''
        Get the cursor for the asset reaction

        :param asset_reaction: the reaction to get the cursor for
        :returns: str
        :raises: ValueError
        '''

        if not isinstance(lite_id, UUID):
            lite_id = UUID(lite_id)

        return AssetReactionStore._get_cursor(
            lite_id, asset_reaction.member_id, asset_reaction.asset_id
        )

    @staticmethod
    def _get_cursor(lite_id: UUID, member_id: UUID, asset_id: UUID) -> str:
        '''
        Get the cursor for the asset reaction

        :param lite_id: UUID of the lite account that is creating the reaction
        :param member_id: UUID of the member who published the asset
        :param asset_id: UUID of the asset that the reaction is for
        :returns: str
        '''

        if not isinstance(member_id, UUID):
            member_id = UUID(member_id)

        if not isinstance(asset_id, UUID):
            asset_id = UUID(asset_id)

        cursor: str = (
            f'{ASSET_REACTIONS_KEY_PREFIX}:{lite_id}_{member_id}_{asset_id}'
        )

        return cursor

    @staticmethod
    def _validate_reaction_key(lite_id: UUID, reaction_key: str) -> None:
        '''
        Validate the reaction key

        :param lite_id: UUID of the lite account that is creating the reaction
        :param member_id: UUID of the member who published the asset
        :param asset_id: UUID of the asset that the reaction is for
        :returns: (none)
        :raises: ValueError if the reaction key is not a valid reaction key
        '''

        if ':' not in reaction_key:
            raise ValueError(f'Invalid reaction key: {reaction_key}')

        parts: list[str] = reaction_key.split(':')
        if len(parts) != 2:
            raise ValueError(f'Invalid reaction key: {reaction_key}')

        if parts[0] != ASSET_REACTIONS_KEY_PREFIX:
            raise ValueError(f'Invalid reaction key: {reaction_key}')

        key: str = parts[1].lstrip(f'{lite_id}')
        cursor: str = key.lstrip('_')
        AssetReactionStore._validate_cursor(cursor)

    @staticmethod
    def _validate_cursor(cursor: str) -> None:
        '''
        Validate the cursor

        :param cursor: as previously returned by get_asset_reaction(s)
        :returns: (none)
        :raises: ValueError if the cursor is not a valid cursor
        '''

        if not isinstance(cursor, str) or len(cursor) != 73:
            raise ValueError(
                f'Invalid cursor: {cursor} is not '
                f'a string of 73 characters'
            )

        parts: list[str] = cursor.split('_')
        if len(parts) != 2:
            raise ValueError(f'Invalid cursor: {cursor}')

        try:
            UUID(parts[0])
        except ValueError:
            raise ValueError(
                f'Invalid cursor: {cursor}, member_id part is not a UUID'
            )

        try:
            UUID(parts[1])
        except ValueError:
            raise ValueError(
                f'Invalid cursor: {cursor}, asset_id part is not a UUID'
            )

    @staticmethod
    def _check_parameters(lite_id: UUID, member_id: UUID | None = None,
                          asset_id: UUID | None = None
                          ) -> None:
        '''
        Check the type and/or value of the parameters

        :param lite_id:
        :param member_id:
        :param asset_id:
        :returns: (none)
        :raises: ValueError
        '''

        if not isinstance(lite_id, UUID):
            lite_id = UUID(lite_id)

        if member_id and not isinstance(member_id, UUID):
            member_id = UUID(member_id)

        if asset_id and not isinstance(asset_id, UUID):
            asset_id = UUID(asset_id)
