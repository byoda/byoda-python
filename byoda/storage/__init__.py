'''
Bring your own algorithm module for backend storage for the server.

The directory server uses caching storage for server and client registrations
The profile server uses NoSQL storage for profile data

:maintainer : Steven Hessing (stevenhessing@live.com)
:copyright  : Copyright 2020, 2021
:license    : GPLv3
'''

from .storage import CacheStorage, CacheStorageType     # noqa
