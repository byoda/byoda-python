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
    NETWORK_DATA         = 'network-data'   # noqa=E221
    ACCOUNTS_CA          = 'accounts-ca'    # noqa=E221
    SERVICES_CA          = 'services-ca'    # noqa=E221
    ACCOUNT              = 'accounts'       # noqa=E221
    MEMBER               = 'members'        # noqa=E221
    SERVICE              = 'services'       # noqa=E221
    SERVICE_CA           = 'service-ca-'    # noqa=E221
    APPS_CA              = "apps-ca-"       # noqa=E221
    MEMBERS_CA           = 'members-ca-'    # noqa=E221
    TLS                  = 'tls'            # noqa=E221
    ACCOUNT_DATA         = 'account-data'   # noqa=E221
    MEMBER_DATA          = 'member-data'    # noqa=E221


EntityId = namedtuple('EntityId', ['id_type', 'uuid', 'service_id'])


class HttpRequestMethod(Enum):
    GET         = 'GET'         # noqa=E221
    POST        = 'POST'        # noqa=E221
    OPTIONS     = 'OPTIONS'     # noqa=E221
    PUT         = 'PUT'         # noqa=E221
    PATCH       = 'PATCH'       # noqa=E221


class CloudType(Enum):
    '''
    At this time only AWS is supported for data persistence
    Use 'LOCAL' when running the pod on your developer
    workstation for testing purposes. All data will be lost
    when you delete the local pod.
    '''
    AWS                  = 'AWS'            # noqa=E221
    GCP                  = 'GCP'            # noqa=E221
    AZURE                = 'Azure'          # noqa=E221
    LOCAL                = 'LOCAL'          # noqa=E221


class CsrSource(Enum):
    WEBAPI         = 1                    # noqa: E221
    LOCAL          = 2                    # noqa: E221


class CertType(Enum):
    NETWORK         = 'network'            # noqa: E221
    NETWORK_DATA    = 'network-data'       # noqa: E221
    ACCOUNT         = 'account'            # noqa: E221
    ACCOUNT_DATA    = 'account-data'       # noqa: E221
    MEMBERSHIP      = 'membership'         # noqa: E221
    MEMBERSHIP_DATA = 'membership-data'    # noqa: E221
    SERVICE         = 'service'            # noqa: E221
    SERVICE_DATA    = 'service-data'       # noqa: E221
    INFRASTRUCTURE  = 'infrastructure'     # noqa: E221
    APP             = 'app'                # noqa: E221
    APP_DATA        = 'app_data'           # noqa: E221


class CertLevel(Enum):
    ROOT           = 'root'               # noqa: E221
    INTERMEDIATE   = 'intermediate'       # noqa: E221
    LEAF           = 'leaf'               # noqa: E221


class CertStatus(Enum):
    NOTFOUND        = 'notfound'          # noqa: E221
    OK              = 'ok'                # noqa: E221
    RENEW           = 'renew'             # noqa: E221
    EXPIRED         = 'expired'           # noqa: E221
