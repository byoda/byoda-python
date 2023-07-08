'''
Non-specific data types

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

# flake8: noqa=E221

from enum import Enum
from uuid import UUID
from collections import namedtuple

# Location to mount the API in the FastApi app and
# to proxy incoming GraphQL requests to other pods
GRAPHQL_API_URL_PREFIX: str = '/api/v1/data/service-{service_id}'

# FastAPI has a bug where the websocket app needs to be under the same path
# as te HTTP app, otherwise it will return a 403. On nginx, we map incoming
# websocket requests for /vs-api/ to /api/ to work around this FastAPI bug.
GRAPHQL_WS_API_URL_PREFIX: str = '/api/v1/data/service-{service_id}'

# Object property to temporarily store the member ID of the
# source of that object
ORIGIN_KEY: str = 'byoda_origin'

# What is the data class for storing network relations
MARKER_NETWORK_LINKS: str = 'network_links'
MARKER_ACCESS_CONTROL: str = '#accesscontrol'


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
    APP_DATA             = 'app-data-'
    ANONYMOUS            = 'anonymous'

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
    RESTRICTED           = 'restricted'

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

class CacheType(Enum):
    QUERY_ID     = 'query'
    COUNTER      = 'counter'
    OBJECT       = 'object'

CounterFilter = dict[str, str | UUID]

class PubSubTech(Enum):
    NNG       = 1

class PubSubMessageType(Enum):
    DATA       = 'data'

class PubSubMessageAction(Enum):
    APPEND      = 'append'
    DELETE      = 'delete'
    MUTATE      = 'mutate'


# StorageType is used for storing files using instances of classes derived
# from FileStorage
class StorageType(Enum):
    PRIVATE     = 'private'
    PUBLIC      = 'public'
    RESTRICTED  = 'restricted'


# ContentType is used by cloud storage drivers to specify the content type
# For local storage, nginx takes care of setting the content type
ContentTypes: dict[str, str] = {
    '.mpd': 'application/dash+xml',
    '.m3u8': 'application/vnd.apple.mpegurl',
    '.mp4': 'video/mp4',
    '.ts': 'video/mp2t',
    '.mpeg': 'video/mpeg',
    '.mov': 'video/quicktime',
    '.webm': 'video/webm',
    '.ogv': 'video/ogg',
    '.avi': 'video/x-msvideo',
    '.m4a': 'audio/mp4',
    '.mp3': 'audio/mpeg',
    '.aac': 'audio/aac',
    '.weba': 'audio/webm',
    '.oga': 'audio/ogg',
    '.wav': 'audio/wav',
    '.webp': 'image/webp',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.tif': 'image/tiff',
    '.tiff': 'image/tiff',
    '.bmp': 'image/bmp',
    '.ttf': 'font/ttf',
    '.otf': 'font/otf',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.xml': 'application/xml',
    '.xhtml': 'application/xhtml+xml',
    '.zip': 'application/zip',
    '.gz': 'application/gzip',
    '.tar': 'application/x-tar',
    '.bz': 'application/x-bzip',
    '.bz2': 'application/x-bzip2',
    '.z': 'application/x-compress',
    '.txt': 'text/plain',
    '.pdf': 'application/pdf',
    '.json': 'application/json',

}

# The following are used for the 'type' parameter in the service schema
class DataType(Enum):
    STRING    = 'string'
    INTEGER   = 'integer'
    NUMBER    = 'number'
    BOOLEAN   = 'boolean'
    UUID      = 'uuid'
    DATETIME  = 'date-time'
    OBJECT    = 'object'
    ARRAY     = 'array'
    REFERENCE = 'reference'


# DataOperationType is a parameter for data objects in the service schema
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


# Search type is a parameter for data objects in the service schema
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

    # flake8: noqa=E221
    NONE        = 'NONE'
    SUCCESS     = 'SUCCESS'
    FAILED      = 'FAILED'


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


class IngestStatus(Enum):
    NONE            = None
    EXTERNAL        = 'external'
    UPLOADED        = 'uploaded'
    ENCODING        = 'encoding'
    DONE            = 'done'
    PUBLISHED       = 'published'
    STARTING        = 'starting'
    DOWNLOADING     = 'downloading'
    PACKAGING       = 'packaging'
    UPLOADING       = 'uploading'
    INGESTED        = 'ingested'
    QUEUED_START    = 'queued_start'

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
