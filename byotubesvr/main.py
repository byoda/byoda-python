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

from byoda.storage.message_queue import Queue

from byoda.datacache.asset_cache import AssetCache

from byoda.util.fastapi import setup_api

from byoda.util.logger import Logger

from byoda import config

from .database.sql import SqlStorage

# from .routers import auth as AuthRouter
from .routers import status as StatusRouter
from byotubesvr.routers import search as SearchRouter
from byotubesvr.routers import data as DataRouter
from byotubesvr.routers import account as AccountRouter

_LOGGER = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    config_file: str = os.environ.get('CONFIG_FILE', 'config-byotube.yml')
    _LOGGER.debug(f'Read configuration file: {config_file}')
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

    config.trace_server = os.environ.get(
        'TRACE_SERVER', config.trace_server
    )

    config.sql_db = await SqlStorage.setup(
        svc_config['svcserver']['litedb']
    )

    config.asset_cache = await AssetCache.setup(
        svc_config['svcserver']['asset_cache']
    )

    redis_rw_url: str = svc_config['svcserver']['asset_cache_readwrite']
    config.asset_cache_readwrite = await AssetCache.setup(redis_rw_url)
    config.email_queue = await Queue.setup(redis_rw_url)

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
    ],
    lifespan=lifespan, trace_server=config.trace_server,
    cors=svc_config['svcserver']['cors_origins']
)

config.app = app
