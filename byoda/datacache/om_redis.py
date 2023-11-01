'''
The KV Redis data cache provides ephemeral data storage, such as services
storing data about their members

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

from typing import Self

from logging import getLogger

from aredis_om.connections import get_redis_connection
from redis_om import Migrator

from redis.exceptions import (
    ConnectionError,
    ExecAbortError,
    PubSubError,
    RedisError,
    ResponseError,
    TimeoutError,
    WatchError,
)

from .kv_cache import DEFAULT_CACHE_EXPIRATION

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)


class OMRedis:
    def __init__(self, identifier: str, expiration: int):
        '''
        Constructor. Do not call directly, use the factory OMRedis.setup()
        instead

        :param identifier: string to include when formatting the key,
        typically this would be the service_id and the name of the cache,
        ie. 'service:{service_id}:assetdb'
        '''

        self.cache_expiration: int = expiration
        self.identifier: str = identifier

        self.driver = None

    async def setup(connection_string: str, identifier: str = None,
                    expiration: int = DEFAULT_CACHE_EXPIRATION) -> Self:
        '''
        Factory for KVRedis class
        '''

        omr = OMRedis(identifier=identifier, expiration=expiration)

        omr.driver = await get_redis_connection(
            url=connection_string,
            retry_on_error=[
                TimeoutError,
                ConnectionError,
                ExecAbortError,
                PubSubError,
                RedisError,
                ResponseError,
                WatchError,
            ],
            protocol=3
        )
        Migrator().run()
        # omr.pipeline = omr.driver.pipeline(transaction=False)
        return omr

    async def close(self):
        await self.driver.close()