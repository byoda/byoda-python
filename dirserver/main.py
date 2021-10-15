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

from byoda.datamodel import DirectoryServer
from byoda.datamodel import Network

from byoda.datastore import DnsDb

from .routers import account
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

server = DirectoryServer()
server.network = Network(
    config.app_config['dirserver'], config.app_config['application']
)
server.load_secrets()
server.network.load_services()
server.network.dnsdb = DnsDb.setup(
    config.app_config['dirserver']['dnsdb'], server.network.name
)

config.server = server


if not os.environ.get('SERVER_NAME') and config.server.network.name:
    os.environ['SERVER_NAME'] = config.server.network.name

app = setup_api(
    'BYODA directory server', 'The directory server for a BYODA network',
    'v0.0.1', config.app_config, [account, service]
)


@app.get('/api/v1/status')
async def status():
    return {'status': 'healthy'}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
