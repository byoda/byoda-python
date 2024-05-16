'''
Class for storing non-account info of BT Lite users, such as
- network_links
- asset_reactions
- comments

Account and billing related data is stored in byotubesvr.database.sqlstorage
class

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from logging import getLogger

from redis import Redis

import redis.asyncio as redis

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)


ASSET_REACTIONS_KEY_PREFIX = 'asset_reactions'
NETWORK_LINKS_KEY_PREFIX = 'network_links'


class LiteStore:
    def __init__(self, connection_string: str) -> None:
        '''
        Use the setup method to create an instance of this class
        '''

        self.connection_string: str = connection_string

        _LOGGER.debug(f'Initialized LiteStore: {connection_string}')

        self.client: Redis[any] = redis.from_url(connection_string)

    async def close(self) -> None:
        await self.client.aclose()
