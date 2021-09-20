'''
Bring your own algorithm module for backend storage for the server.

The directory server uses caching storage for server and client registrations
The profile server uses NoSQL storage for profile data

:maintainer : Steven Hessing (steven@byoda.org)
:copyright  : Copyright 2020, 2021
:license    : GPLv3
'''

# flake8: noqa=E401

from .aws import AwsFileStorage
from .filestorage import FileStorage, FileMode
