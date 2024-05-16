'''
API server for Bring Your Own Tube application

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import os
import sys

from typing import AsyncGenerator
from contextlib import asynccontextmanager

from yaml import safe_load as yaml_safe_loader

from fastapi import FastAPI

from fastapi_limiter import FastAPILimiter

import redis.asyncio as redis

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from byoda.storage.message_queue import Queue

from byoda.datacache.asset_cache import AssetCache
from byoda.datacache.channel_cache import ChannelCache

from byoda.util.fastapi import setup_api

from byoda.util.logger import Logger

from byoda import config

from .database.sql import SqlStorage

from .database.network_link_store import NetworkLinkStore
from .database.asset_reaction_store import AssetReactionStore

# from .routers import auth as AuthRouter
from byotubesvr.models.lite_account import LiteAccountSqlModel

from byotubesvr.routers import status as StatusRouter
from byotubesvr.routers import search as SearchRouter
from byotubesvr.routers import data as DataRouter
from byotubesvr.routers import account as AccountRouter
from byotubesvr.routers import network_link as NetworkLinkRouter
from byotubesvr.routers import asset_reaction as AssetReactionRouter

_LOGGER = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    config_file: str = os.environ.get('CONFIG_FILE', 'config-byotube.yml')
    with open(config_file) as file_desc:
        svc_config: dict[str, str | int | bool | None] = yaml_safe_loader(
            file_desc
        )

    debug: bool = svc_config['application'].get('debug', False)
    verbose: bool = not debug
    config.debug = debug

    global _LOGGER
    _LOGGER = Logger.getLogger(
        sys.argv[0], debug=debug, verbose=verbose,
        logfile=svc_config['svcserver'].get('logfile')
    )

    _LOGGER.debug(f'Read configuration file: {config_file}')

    config.trace_server = os.environ.get(
        'TRACE_SERVER', config.trace_server
    )

    config.jwt_secrets = svc_config['svcserver']['jwt_secrets']

    lite_db: SqlStorage = await SqlStorage.setup(
        svc_config['svcserver']['lite_db']
    )
    config.lite_db = lite_db
    for cls in [LiteAccountSqlModel]:
        await cls.create_table(lite_db)

    config.asset_cache = await AssetCache.setup(
        svc_config['svcserver']['asset_cache']
    )
    redis_rw_url: str = svc_config['svcserver']['asset_cache_readwrite']
    config.asset_cache_readwrite = await AssetCache.setup(redis_rw_url)

    config.channel_cache = await ChannelCache.setup(
        svc_config['svcserver']['channel_cache']
    )
    redis_rw_url: str = svc_config['svcserver']['channel_cache_readwrite']
    config.channel_cache_readwrite = await ChannelCache.setup(redis_rw_url)

    config.email_queue = await Queue.setup(redis_rw_url)

    config.network_link_store = NetworkLinkStore(
        svc_config['svcserver']['lite_store']
    )
    config.asset_reaction_store = AssetReactionStore(
        svc_config['svcserver']['lite_store']
    )

    redis_connection: redis.Redis = redis.from_url(
        redis_rw_url, encoding='utf-8'
    )
    await FastAPILimiter.init(
        redis=redis_connection, prefix='ratelimits'
    )

    secret: dict[str, str] = svc_config['svcserver']['jwt_asym_secrets'][0]
    with open(secret['cert_file'], 'rb') as file_desc:
        cert: x509.Certificate = x509.load_pem_x509_certificate(
            file_desc.read()
        )
    with open(secret['key_file'], 'rb') as file_desc:
        data: bytes = file_desc.read()
        key: RSAPrivateKey = serialization.load_pem_private_key(
            data, str.encode(secret['passphrase'])
        )
    config.jwt_asym_secrets = [(cert, key)]

    _LOGGER.info('Starting server')

    yield

    _LOGGER.info('Shutting down server')


config_file: str = os.environ.get('CONFIG_FILE', 'config-byotube.yml')
with open(config_file) as file_desc:
    svc_config: dict[str, str | int | bool | None] = yaml_safe_loader(
        file_desc
    )

app: FastAPI = setup_api(
    'BYO.Tube app server',
    'BYO.Tube application server hosting authenticated and anonymous apis'
    'network', 'v0.0.1',
    [
        StatusRouter,
        AccountRouter,
        DataRouter,
        SearchRouter,
        NetworkLinkRouter,
        AssetReactionRouter,
    ],
    lifespan=lifespan, trace_server=config.trace_server,
    cors=svc_config['svcserver']['cors_origins']
)

config.app = app
