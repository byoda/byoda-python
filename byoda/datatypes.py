'''
Non-specific data types

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

from enum import Enum


class ServerRole(Enum):
    RootCa               = 'root_ca'        # noqa=E211
    DirectoryServer      = 'directory'      # noqa=E211
    ServiceCa            = "service_ca"     # noqa=E211
    ServiceServer        = 'service'        # noqa=E111
    ContentServer        = 'content'        # noqa=E211
    Pod                  = 'pod'            # noqa=E111
    Client               = 'client'         # noqa=E111


class IdType(Enum):
    ACCOUNT              = 'accounts'       # noqa=E111
    MEMBER               = 'members'        # noqa=E111
    SERVICE              = 'services'       # noqa=E111
