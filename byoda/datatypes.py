'''
Non-specific data types

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

# flake8: noqa=E221

from enum import Enum
from collections import namedtuple
from os import stat


class ServerRole(Enum):
    RootCa               = 'root_ca'
    DirectoryServer      = 'directory'
    ServiceCa            = 'services_ca'
    ServiceServer        = 'service'
    ContentServer        = 'content'
    Pod                  = 'pod'
    Client               = 'client'


class IdType(Enum):
    SERVICE_DATA         = 'service-data-'
    NETWORK_DATA         = 'network-data'
    ACCOUNTS_CA          = 'accounts-ca'
    ACCOUNT_DATA         = 'account-data'
    MEMBER_DATA          = 'member-data-'
    SERVICES_CA          = 'services-ca'
    SERVICE_CA           = 'service-ca-'
    MEMBERS_CA           = 'members-ca-'
    APPS_CA              = 'apps-ca-'
    ACCOUNT              = 'accounts'
    MEMBER               = 'members-'
    SERVICE              = 'service-'
    APP                  = 'apps-'

    @staticmethod
    def by_value_lengths():
        return sorted(list(IdType), key=lambda k: len(k.value), reverse=True)

# The UUID is the value for the specified IdType, ie with IdType.MEMBER
# the uuid is for the member_id. The service_id field then specifies
# the service the uuid is a member of
EntityId = namedtuple('EntityId', ['id_type', 'id', 'service_id'])


class HttpRequestMethod(Enum):
    GET         = 'GET'
    POST        = 'POST'
    OPTIONS     = 'OPTIONS'
    PUT         = 'PUT'
    PATCH       = 'PATCH'


class CloudType(Enum):
    '''
    At this time only AWS is supported for data persistence
    Use 'LOCAL' when running the pod on your developer
    workstation for testing purposes. All data will be lost
    when you delete the local pod.
    '''
    AWS                  = 'AWS'
    GCP                  = 'GCP'
    AZURE                = 'Azure'
    LOCAL                = 'LOCAL'


class CsrSource(Enum):
    WEBAPI         = 1
    LOCAL          = 2


class CertType(Enum):
    NETWORK         = 'network'
    NETWORK_DATA    = 'network-data'
    ACCOUNT         = 'account'
    ACCOUNT_DATA    = 'account-data'
    MEMBERSHIP      = 'membership'
    MEMBERSHIP_DATA = 'membership-data'
    SERVICE         = 'service'
    SERVICE_DATA    = 'service-data'
    INFRASTRUCTURE  = 'infrastructure'
    APP             = 'app'
    APP_DATA        = 'app_data'


class CertLevel(Enum):
    ROOT           = 'root'
    INTERMEDIATE   = 'intermediate'
    LEAF           = 'leaf'


class CertStatus(Enum):
    NOTFOUND        = 'notfound'
    OK              = 'ok'
    RENEW           = 'renew'
    EXPIRED         = 'expired'
