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

from byoda.datamodel import ServiceServer
from byoda.datamodel import Service
from byoda.datamodel import Network

from .routers import service

_LOGGER = None

with open('config.yml') as file_desc:
    config.app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

debug = config.app_config['application']['debug']
verbose = not debug
_LOGGER = Logger.getLogger(
    sys.argv[0], debug=debug, verbose=verbose,
    logfile=config.app_config['application'].get('logfile')
)

network = Network(
    config.app_config['svcserver'], config.app_config['application']
)
server = ServiceServer()
server.service = Service(
    network, config.app_config['svcserver']['service_file'],
    config.app_config['svcserver']['service_id']
)
server.load_secrets(
    password=config.app_config['svcserver']['private_key_password']
)
server.service.load_schema(verify_contract_signatures=True)

config.server = server

if not os.environ.get('SERVER_NAME') and config.server.network.name:
    os.environ['SERVER_NAME'] = config.server.network.name

app = setup_api(
    'BYODA service server', 'A server hosting a service in a BYODA network',
    'v0.0.1', config.app_config, [service]
)


@app.get('/api/v1/status')
async def status():
    return {'status': 'healthy'}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=6000)
