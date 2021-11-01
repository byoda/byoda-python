'''
API server for Bring Your Own Data and Algorithms

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import sys
import yaml
import uvicorn

from .api import setup_api

from byoda.util.logger import Logger
from byoda import config

from byoda.servers import ServiceServer
from byoda.datamodel import Service
from byoda.datamodel import Network

from byoda.util import Paths

from .routers import service

_LOGGER = None

# We support the
config_file = os.environ.get('CONFIG_FILE', 'config.yml')
with open(config_file) as file_desc:
    config.app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

debug = config.app_config['application']['debug']
verbose = not debug
_LOGGER = Logger.getLogger(
    sys.argv[0], debug=debug, verbose=verbose,
    logfile=config.app_config['svcserver'].get('logfile')
)
_LOGGER.debug(f'Read configuration file: {config_file}')

server = ServiceServer()

server.network = Network(
    config.app_config['svcserver'], config.app_config['application']
)
server.service = Service(
    server.network, None, config.app_config['svcserver']['service_id']
)
server.load_secrets(
    password=config.app_config['svcserver']['private_key_password']
)
server.service.tls_secret.save_tmp_private_key()

schema_file = server.service.paths.get(Paths.SERVICE_FILE)
server.service.load_schema(
    filepath=schema_file, verify_contract_signatures=True
)

if not os.environ.get('SERVER_NAME') and server.network.name:
    os.environ['SERVER_NAME'] = server.network.name

config.server = server

app = setup_api(
    'BYODA service server', 'A server hosting a service in a BYODA network',
    'v0.0.1', config.app_config, [service]
)


@app.get('/api/v1/status')
async def status():
    return {'status': 'healthy'}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=6000)
