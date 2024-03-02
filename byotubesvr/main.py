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

from byoda.util.fastapi import setup_api

from byoda.util.logger import Logger

from byoda import config

# from .routers import auth as AuthRouter
from .routers import status as StatusRouter

_LOGGER = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    config_file: str = os.environ.get('CONFIG_FILE', 'config-byotube.yml')
    with open(config_file) as file_desc:
        app_config: dict[str, str | int | bool | None] = yaml_safe_loader(
            file_desc
        )

    debug: bool = app_config['application'].get('debug', False)
    verbose: bool = not debug
    config.debug = debug

    global _LOGGER
    _LOGGER = Logger.getLogger(
        sys.argv[0], debug=debug, verbose=verbose,
        logfile=app_config['appserver'].get('logfile')
    )
    _LOGGER.debug(f'Read configuration file: {config_file}')

    _LOGGER.info('Starting server')

    yield

    _LOGGER.info('Shutting down server')


config_file: str = os.environ.get('CONFIG_FILE', 'config-byotube.yml')
with open(config_file) as file_desc:
    app_config: dict[str, str | int | bool | None] = yaml_safe_loader(
        file_desc
    )

app: FastAPI = setup_api(
    'BYO.Tube app server',
    'BYO.Tube application server hosting authenticated and anonymous apis'
    'network', 'v0.0.1',
    [
        StatusRouter,
    ],
    lifespan=lifespan, trace_server=config.trace_server,
    cors=app_config['appserver']['cors_origins']
)

config.app = app
