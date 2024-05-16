'''
Non-specific data types

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

# flake8: noqa=E221

from enum import Enum
from uuid import UUID
from typing import Self
from datetime import datetime
from datetime import time
from datetime import date
from collections import namedtuple

# Location to proxy incoming REST Date requests to other pods
DATA_API_URL: str = \
    '{protocol}://{fqdn}:{port}/api/v1/data/{service_id}/{class_name}/{action}'

DATA_WS_API_URL: str = \
    'wss://{fqdn}:{port}/ws-api/v1/data/{service_id}/{class_name}/{action}'

DATA_WS_API_INTERNAL_URL: str = \
    'ws://127.0.0.1:{port}/api/v1/data/{service_id}/{class_name}/{action}'

# FastAPI has a bug where the websocket app needs to be under the same path
# as te HTTP app, otherwise it will return a 403. In the angie configuration,
# we map incoming websocket requests for /vs-api/ to /api/ to work around this
# FastAPI bug.
DATA_API_PROXY_URL: str = \
    '{protocol}://proxy.{network}/{service_id}/{member_id}/api/v1/data/{service_id}/{class_name}/{action}'

# Object property to temporarily store the member ID of the
# source of that object
ORIGIN_KEY: str = 'byoda_origin'

# What is the data class for storing network relations
MARKER_NETWORK_LINKS: str = 'network_links'

# The data class where logs for REST Data API calls are stored
MARKER_DATA_LOGS: str = 'datalogs'

# The property used to specify access controls for data classes
MARKER_ACCESS_CONTROL: str = '#accesscontrol'

# How many records should a Data query return by default
DEFAULT_QUERY_SIZE: int = 40

# Where the pod stores the decrypted ssl key so that angie can access it
TEMP_SSL_DIR: str = '/var/tmp/ssl'

MemberInfo: namedtuple = namedtuple(
    'MemberInfo', ['member_id', 'service_id', 'status', 'timestamp']
)
NetworkLink: namedtuple = namedtuple(
    'NetworkLink', [
        'member_id', 'relation', 'created_timestamp', 'annotations',
        'last_health_api_success'
    ]
)

AnyScalarType = \
    str | bytes | int | float | bool | UUID | datetime | date | time

DataFilterType = dict[str, dict[str, AnyScalarType]]

DataDictType = dict[str, object]


class ServerRole(Enum):
    RootCa               = 'root_ca'
    DirectoryServer      = 'directory'
    ServiceCa            = 'services_ca'
    ServiceServer        = 'service'
    ContentServer        = 'content'
    App                  = 'app'
    Pod                  = 'pod'
    Client               = 'client'
    Test                 = 'test'


class ServerType(Enum):
    POD         = 'pod'
    DIRECTORY   = 'directory'
    SERVICE     = 'service'
    APP         = 'app'


class AppType(Enum):
    MODERATE    = 'moderate'
    CDN         = 'cdn'
    IDENTITY    = 'identity'
    PAYMENT     = 'payment'


class ClaimStatus(Enum):
    PENDING     = 'pending'      # When claim is submitted
    ACCEPTED    = 'accepted'     # when claim is accepted
    WITHDRAWN   = 'withdrawn'    # when previously accepted claim is withdrawn
    REJECTED    = 'rejected'     # when a submitted claim is rejected


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
    BTLITE               = 'btlite'

    @staticmethod
    def by_value_lengths() -> list[Self]:
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


class MailType(Enum):
    '''
    The type of email message that we want to send to user
    '''

    EMAIL_VERIFICATION   = 'email_verification'
    PASSWORD_RESET       = 'password_reset'
    TWO_FACTOR_AUTH      = 'two_factor_auth'


# From BYO.Tube service contract
class MonetizationType(Enum):
    # flake8: noqa: E221
    FREE            = 'free'
    BURSTPOINTS     = 'burstpoints'
    SUBSCRIPTION    = 'subscription'
    PPV             = 'ppv'
    SPPV            = 'sppv'
    PREROLL_AD      = 'preroll_ad'


# From byopay.payserver.util.datatypes
class Currency(Enum):
    USD = 'USD'
    EUR = 'EUR'
    UKP = 'UKP'
    CAD = 'CAD'
    AUD = 'AUD'
    NZD = 'NZD'
    CNY = 'CNY'
    HKD = 'HKD'
    SGD = 'SD'
    MYR = 'RM'
    CHF = 'CHF'
    DKK = 'DKK'
    NOK = 'NOK'
    SEK = 'SEK'
    JPY = 'JPY'
    PLN = 'PLN'
    CZK = 'CZK'


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
    DATA         = 'data'
    ASSET        = 'asset'
    ASSETDB      = 'AssetDb'
    MEMBERDB     = 'MemberDb'
    SEARCHDB     = 'SearchDb'

# Type of item to store in the searchable_cache
class ItemType(Enum):
    ASSET       =  'assets'
    CHANNEL     =  'channels'

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

# This data is used to generate names of external urls for YouTube channels
# The keys of the dict are the name of the social network in its URL
SocialNetworks: dict[str, str] = {
    'facebook': 'Facebook',
    'twitter': 'Twitter',
    'x': 'X',
    'instagram': 'Instagram',
    'youtube': 'YouTube',
    'linkedin': 'LinkedIn',
    'pinterest': 'Pinterest',
    'tumblr': 'tumblr',
    'reddit': 'reddit',
    'snapchat': 'Snapchat',
    'flickr': 'flickr',
    'tiktok': 'TikTok',
    'whatsapp': 'WhatsApp',
    'telegram': 'Telegram',
    'signal': 'Signal',
    'messenger': 'messenger',
    'parler': 'Parler',
    'gab': 'Gab',
    'rumble': 'Rumble',
    'patreon': 'Patreon',
    'twitch': 'twitch',
    'spotify': 'Spotify',
    'discord': 'Discord',
    'slack': 'Slack',
    'nebula': 'Nebula',
    'wechat': 'WeChat',
    'douyin': 'Douyin',
    'kuaishou': 'Kuaishou',
    'weibo': 'Weibo',
    'qq': 'QQ',
    'qzone': 'Qzone',
    'myjosh': 'Josh',
    'microsoft': 'Teams',
    'quora': 'Quora',
    'skype': 'Skype',
    'tieba': 'Tieba',
    'baidu': 'Baidu',
    'viber': 'Viber',
    'line': 'Line',
    'imo': 'Imo',
    'xiaohongshu': 'Xiaohongshu',
    'likee': 'Likee',
    'picsart': 'Picsart',
    'soundcloud': 'SoundCloud',
    'onlyfans': 'OnlyFans',
    'vevo': 'Vevo',
    'vk': 'VK',
    'threads': 'Threads',
    'zoom': 'Zoom',
    'meet': 'Meet',
    'clubhouse': 'Clubhouse',
    'imessage': 'iMessage',
    'facetime': 'FaceTime',
    'byo': 'BYO.Tube',
    'steampowered': 'Steam',
    'linktr.ee': 'Linktree',
    'amzn': 'Amazon',
    'amazon': 'Amazon',
}

TwoLevelTLDs: list[str] = [
    'uk', 'nz', 'au', 'ca', 'us', 'eu', 'de', 'fr', 'it', 'es', 'pt', 'br',
]

# ContentType is used by cloud storage drivers to specify the content type
# For local storage, angie takes care of setting the content type
ContentTypesByExtension: dict[str, str] = {
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

ContentTypesByType: dict[str, str] = {
    'application/dash+xml': '.mpd',
    'application/vnd.apple.mpegurl': '.m3u8',
    'video/mp4': '.mp4',
    'video/mp2t': '.ts',
    'video/mpeg': '.mpeg',
    'video/quicktime': '.mov',
    'video/webm': '.webm',
    'video/ogg': '.ogv',
    'video/x-msvideo': '.avi',
    'audio/mp4': '.m4a',
    'audio/mpeg': '.mp3',
    'audio/aac': '.aac',
    'audio/webm': '.weba',
    'audio/ogg': '.oga',
    'audio/wav': '.wav',
    'image/webp': '.webp',
    'image/jpeg': '.jpg',
    'image/png':'.png',
    'image/svg+xml': '.svg',
    'image/x-icon': '.ico',
    'image/tiff': '.tif',
    'image/bmp': '.bmp',
    'font/ttf': '.ttf',
    'font/otf': '.otf',
    'font/woff': '.woff',
    'font/woff2': '.woff2',
    'application/xml': '.xml',
    'application/xhtml+xml': '.xhtml',
    'application/zip': '.zip',
    'application/gzip': '.gz',
    'application/x-tar': '.tar',
    'application/x-bzip': '.bz',
    'application/x-bzip2': '.bz2',
    'application/x-compress': '.z',
    'text/plain': '.txt',
    'application/pdf': '.pdf',
    'application/json': '.json',
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


# The values for DataRequestType are used for the signatures
# for the REST Data APIs
class DataRequestType(Enum):
    QUERY               = 'query'
    MUTATE              = 'mutate'      # mutate an object
    APPEND              = 'append'
    UPDATE              = 'update'      # mutate an object in an array
    DELETE              = 'delete'
    COUNTER             = 'counter'
    UPDATES             = 'updates'


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
    # Allows subscribing to data changes
    SUBSCRIBE   = "subscribe"

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
    TLS status as reported by angie variable 'ssl_client_verify':
    http://angie.org/en/docs/http/ngx_http_ssl_module.html#var_ssl_client_verify
    Angie ssl_verify_client is configured for 'optional' or 'on'. M-TLS client
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
    UNAVAILABLE     = 'unavailable'

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


class DnsRecordType(Enum):
    A = 'A'
    TXT = 'TXT'
