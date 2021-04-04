'''
Non-specific data types

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

from enum import Enum
from collections import namedtuple


class ServerRole(Enum):
    RootCa               = 'root_ca'        # noqa=E221
    DirectoryServer      = 'directory'      # noqa=E221
    ServiceCa            = 'services_ca'    # noqa=E221
    ServiceServer        = 'service'        # noqa=E221
    ContentServer        = 'content'        # noqa=E221
    Pod                  = 'pod'            # noqa=E221
    Client               = 'client'         # noqa=E221


class IdType(Enum):
    ACCOUNT              = 'accounts'       # noqa=E221
    MEMBER               = 'members'        # noqa=E221
    SERVICE              = 'services'       # noqa=E221
    ACCOUNTS_CA          = 'accounts-ca'    # noqa=E221
    SERVICES_CA          = 'services-ca'    # noqa=E221
    SERVICE_CA           = 'service-ca-'    # noqa=E221
    MEMBERS_CA           = 'members-ca-'    # noqa=E221


EntityId = namedtuple('EntityId', ['id_type', 'uuid', 'service_id'])


class CloudType(Enum):
    AWS                  = 'AWS'            # noqa=E221
    GCP                  = 'GCP'            # noqa=E221
    AZURE                = 'Azure'          # noqa=E221


class CsrSource(Enum):
    WEBAPI         = 1                    # noqa: E221
    LOCAL          = 2                    # noqa: E221


class CertType(Enum):
    NETWORK        = 'network'            # noqa: E221
    ACCOUNT        = 'account'            # noqa: E221
    MEMBERSHIP     = 'membership'         # noqa: E221
    SERVICE        = 'service'            # noqa: E221
    INFRASTRUCTURE = 'infrastructure'     # noqa: E221


class CertLevel(Enum):
    ROOT           = 'root'               # noqa: E221
    INTERMEDIATE   = 'intermediate'       # noqa: E221
    LEAF           = 'leaf'               # noqa: E221
