'''
config

provides global variables

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from typing import TypeVar

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from httpx import AsyncClient as AsyncHttpClient
from httpx import Client as SyncClient

from ssl import SSLContext

from opentelemetry.metrics import Meter

from prometheus_client import Counter
from prometheus_client import Gauge

from byoda.datatypes import IdType

from byoda.storage.message_queue import Queue

from byoda.servers.server import Server

from byotubesvr.database.sql import SqlStorage

DEFAULT_NETWORK: str = 'byoda.net'

SERVICE_ID: int = 16384

HttpSession = TypeVar('HttpSession')

SettingsStore = TypeVar('SettingsStore')
NetworkLinkStore = TypeVar('NetworkLinkStore')
AssetReactionStore = TypeVar('AssetReactionStore')

Secret = TypeVar('Secret')
FastAPI = TypeVar('FastAPI')
AssetCache = TypeVar('AssetCache')
ChannelCache = TypeVar('ChannelCache')

# Enable various debugging options in the pod, including
# whether the OpenAPI web pages should be enabled.
debug: bool = False

# Used by logging to add extra data to each log record,
# typically using the byoda.util.logger.flask_log_fields
# decorator
# After importing config, you can also set, for example,
# config.extra_log_data['remote_addr'] = client_ip
extra_log_data: dict[str, str] = {}

# The configuration of the server, its peers and the networks
# it is supporting
server: Server = None

# The FastAPI app, used to add routes to REST Data APIs
# while the server is running
app: FastAPI = None

# global session manager, apparently not 100% thread-safe if
# using different headers, cookies etc.
request: SyncClient = SyncClient()

# Test cases set the value to True. Code may evaluate whether
# it is running as part of a test case to accept function parameters
test_case: bool = False

# Write logs about data requests?
log_requests: bool = True

# Disables PubSub for testing purposes
disable_pubsub: bool = False

# Pool of HTTPX Async Client sessions, used by pods and service- and directory
# server:
client_pools: dict[str, AsyncHttpClient] = {}

# Pool of requests sessions, used by pod_worker as it can't use asyncio.
sync_client_pools: dict[str, SyncClient] = {}

# This cache avoids having to load cert/key for each request that uses
# client SSL auth
ssl_contexts: dict[str, SSLContext] = {}

# Setting for OpenTelemetry tracing
trace_server: str = '127.0.0.1'

# Meter for OpenTelemetry-based prometheus exporter
meter: Meter | None = None

# Metrics for native prometheus exporters. We don't instantiate specific
# metrics here as workers use prometheus-exporter module while app servers
# use OpenTelemetry prometheus exporter
metrics: dict[str, Counter | Gauge] = {}


#
# Used by BYO.Tube Lite server:
#
asset_cache: AssetCache | None = None
asset_cache_readwrite: AssetCache | None = None

channel_cache: ChannelCache | None = None
channel_cache_readwrite: ChannelCache | None = None

# The PostgreSql database for BYO.Tube Lite account-level data
lite_db: SqlStorage | None = None

# The Redis database for non-critical BYO.Tube Lite account data
network_link_store: NetworkLinkStore = None
asset_reaction_store: AssetReactionStore = None
settings_store: SettingsStore = None

# The Lite server generates verification urls with this variable
verification_url: str = 'https://www.byo.tube/verify-email'


# Queue for communication between appserver and byotubesvr/email_worker.py
# to send emails for email verification, password reset etc.
email_queue: Queue | None = None

# (Symmetric) secrets for BYOtube.lite JWTs
jwt_secrets: list[str] = []

# Secret for calling APIs on pods
service_secret: Secret | None = None

# Assymetric secret for BYOTube.lite 3rd-party / App JWTs
jwt_asym_secrets: list[tuple[x509.Certificate, RSAPrivateKey]] = []

# Data certs used to verify claim signatures. The fingerprint of the
# cert is used as the key in this dict.
data_certs: dict[str, dict[IdType, x509.Certificate]] = {}
