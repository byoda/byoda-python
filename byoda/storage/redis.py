'''
Bring your own algorithm cache storage for the server based on Redis.

The directory server uses caching storage for server and client registrations

:maintainer : Steven Hessing (stevenhessing@live.com)
:copyright  : Copyright 2020, 2021
:license    : GPLv3
'''

import logging

import redis

from . import CacheStorage

_LOGGER = logging.getLogger(__name__)


class RedisCacheStorage(CacheStorage):
    def __init__(self):
        super().__init__()

    @staticmethod
    def connect(config):
        cache = RedisCacheStorage()

        host = config['host']
        port = config.get('port', 6379)
        password = config.get('password', None)

        cache.server = redis.Redis(
            host=host, port=port, password=password
        )

        return cache

    def get(self, key):
        self.server.get(key)

    def set(self, key, value):
        self.server.set(key, value)

    def incr(self, key):
        self.server.incr(key)

    def incrby(self, key, value):
        self.server.incrby(key, value)

    def decr(self, key):
        self.server.incr(key)

    def decrby(self, key, value):
        self.server.incr(key, value)

    def exists(self, key):
        self.server.exists

    def delete(self, key):
        self.server.delete(key)
