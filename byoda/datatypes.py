'''
Non-specific data types

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

# flake8: noqa=E221

from enum import Enum
from collections import namedtuple

# Location to mount the API in the FastApi app and
# to proxy incoming GraphQL requests to other pods
GRAPHQL_API_URL_PREFIX = '/api/v1/data/service-{service_id}'
# FastAPI has a bug where the websocket app needs to be under the same path
# as te HTTP app, otherwise it will return a 403.
GRAPHQL_WS_API_URL_PREFIX = '/api/v1/data/service-{service_id}'

# Object property to temporarily store the member ID of the
# source of that object
ORIGIN_KEY = 'byoda_origin'


class ServerRole(Enum):
    RootCa               = 'root_ca'
    DirectoryServer      = 'directory'
    ServiceCa            = 'services_ca'
    ServiceServer        = 'service'
    ContentServer        = 'content'
    Pod                  = 'pod'
    Client               = 'client'
    Test                 = 'test'


class ServerType(Enum):
    POD         = 'pod'
    DIRECTORY   = 'directory'
    SERVICE     = 'service'


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

class RightsEntityType(Enum):
    MEMBER               = 'member'
    SERVICE              = 'service'
    NETWORK              = 'network'
    ANY_MEMBER           = 'any_member'
    ANONYMOUS            = 'anonymous'

class VisibilityType(Enum):
    PRIVATE              = 'private'
    MEMBER               = 'member'
    KNOWN                = 'known'
    PUBLIC               = 'public'

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

class CacheTech(Enum):
    REDIS       = 1
    SQLITE      = 2

class PubSubTech(Enum):
    NNG       = 1

class StorageType(Enum):
    PRIVATE = 'private'
    PUBLIC = 'public'

class DataType(Enum):
    # flake8: noqa=E221
    STRING    = 'string'
    INTEGER   = 'integer'
    NUMBER    = 'number'
    BOOLEAN   = 'boolean'
    UUID      = 'uuid'
    DATETIME  = 'date-time'
    OBJECT    = 'object'
    ARRAY     = 'array'
    REFERENCE = 'reference'


class DataOperationType(Enum):
    # flake8: noqa=E221
    CREATE      = 'create'
    READ        = 'read'
    UPDATE      = 'update'
    DELETE      = 'delete'
    APPEND      = 'append'
    SEARCH      = 'search'
    PERSIST     = 'persist'
    # Mutate can be either create, update, append or delete
    MUTATE      = 'mutate'


class SearchType(Enum):
    # flake8: noqa=E221
    EXACT      = 'exact'
    SUBSTRING  = 'substring'
    STARTSWITH = 'startswith'
    ENDSWITH   = 'endswith'
    REGEX      = 'regex'

class TlsStatus(str, Enum):
    '''
    TLS status as reported by nginx variable 'ssl_client_verify':
    http://nginx.org/en/docs/http/ngx_http_ssl_module.html#var_ssl_client_verify
    Nginx ssl_verify_client is configured for 'optional' or 'on'. M-TLS client
    certs must always be signed as we do not configure 'optional_no_ca' so
    'FAILED' requests should never make it to the application service
    '''

    NONE        = 'NONE'        # noqa: E221
    SUCCESS     = 'SUCCESS'     # noqa: E221
    FAILED      = 'FAILED'      # noqa: E221


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


class AuthSource(Enum):
    NONE            = 'none'
    CERT            = 'cert'
    TOKEN           = 'token'


# MemberStatus is used for the MemberDB.status attribute
class MemberStatus(Enum):
    # flake8: noqa=E221
    # We don't know what is going on
    UNKNOWN         = 'UNKNOWN'
    # Client called POST service/member API
    SIGNED          = 'SIGNED'
    # Client has called PUT service/member or network/member API
    REGISTERED      = 'REGISTERED'
    # Client has called DELETE service/member or network/member API
    DELETED         = 'DELETED'
    # Service (worker) was unable to query the client
    ACTIVE      = 'active'     # Currently a member
    PAUSED      = 'paused'     # paused without data deletion
    REMOVED     = 'removed'    # no longer a member, data not deleted

class ReviewStatusType(Enum):
    ACCEPTED        = 'ACCEPTED'
    REJECTED        = 'REJECTED'
