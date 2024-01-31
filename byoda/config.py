'''
config

provides global variables

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from typing import TypeVar

from httpx import AsyncClient as AsyncHttpClient
from httpx import Client as SyncClient

from ssl import SSLContext

from fastapi import FastAPI

from prometheus_client import Counter
from prometheus_client import Gauge

from byoda.servers.server import Server


DEFAULT_NETWORK = 'byoda.net'

HttpSession = TypeVar('HttpSession')

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

# Metrics for exporters. We don't instantiate specific metrics here
# as workers use prometheus-exporter module while app servers should
# use OpenTelemetry prometheus exporter
metrics: dict[str, Counter | Gauge] = {}
