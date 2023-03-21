#!/usr/bin/python3

'''
Worker that performs queries against registered members of
the service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import sys
import yaml
import asyncio

from uuid import uuid4

from datetime import datetime, timedelta, timezone

from python_graphql_client import GraphqlClient
from requests.exceptions import ConnectionError as RequestConnectionError
from requests.exceptions import HTTPError

from byoda.servers.service_server import ServiceServer

from byoda.datamodel.network import Network

from byoda.datatypes import GRAPHQL_API_URL_PREFIX
from byoda.util.paths import Paths

from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS

from byoda import config

from byoda.util.logger import Logger

MAX_WAIT = 15 * 60
MEMBER_PROCESS_INTERVAL = 8 * 60 * 60

BASE_URL = (
    'https://{member_id}.members-{service_id}.{network}' +
    GRAPHQL_API_URL_PREFIX
)


async def main():
    config_file = os.environ.get('CONFIG_FILE', 'config.yml')
    with open(config_file) as file_desc:
        app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

    global _LOGGER
    debug = app_config['application']['debug']
    _LOGGER = Logger.getLogger(
        sys.argv[0], json_out=True,
        debug=app_config['application'].get('debug', False),
        loglevel=app_config['application'].get('loglevel', 'INFO'),
        logfile=app_config['svcserver'].get('worker_logfile')
    )

    if debug:
        global MAX_WAIT
        MAX_WAIT = 300

    network = Network(
        app_config['svcserver'], app_config['application']
    )
    network.paths = Paths(
        network=network.name,
        root_directory=app_config['svcserver']['root_dir']
    )
    server = ServiceServer(network, app_config)
    await server.load_network_secrets()

    await server.load_secrets(
        password=app_config['svcserver']['private_key_password']
    )
    config.server = server
    service = server.service
    try:
        unprotected_key_file = service.tls_secret.save_tmp_private_key()
    except PermissionError:
        _LOGGER.info(
            'Could not write unprotected key, probably because it '
            'already exists'
        )
        unprotected_key_file = f'/tmp/service-{service.service_id}.key'

    certkey = (
        service.paths.root_directory + '/' + service.tls_secret.cert_file,
        unprotected_key_file
    )
    root_ca_certfile = (
        f'{service.paths.root_directory}/{service.network.root_ca.cert_file}'
    )

    if not await service.paths.service_file_exists(service.service_id):
        await service.download_schema(save=True)

    await server.load_schema(verify_contract_signatures=False)

    _LOGGER.debug(
        f'Starting service worker for service ID: {service.service_id}'
    )

    while True:
        member_id = server.member_db.get_next(timeout=MAX_WAIT)
        if not member_id:
            _LOGGER.debug('No member available in list of members')
            continue

        server.member_db.add_member(member_id)
        _LOGGER.debug(f'Processing member_id {member_id}')
        try:
            data = server.member_db.get_meta(member_id)
        except (TypeError, KeyError) as exc:
            _LOGGER.warning(f'Invalid data for member: {member_id}: {exc}')
            continue

        server.member_db.add_meta(
            data['member_id'], data['remote_addr'], data['schema_version'],
            data['data_secret'], data['status']
        )

        waittime = next_member_wait(data['last_seen'])

        #
        # Here is where we can do stuff
        #

        url = BASE_URL.format(
            member_id=str(member_id), service_id=service.service_id,
            network=service.network.name
        )
        client = GraphqlClient(
            endpoint=url, cert=certkey, verify=root_ca_certfile
        )
        try:
            result = client.execute(
                query=GRAPHQL_STATEMENTS['person']['query'],
                variables={'query_id': uuid4()}
            )
            if result.get('data'):
                edges = result['data']['person_connection']['edges']
                if not edges:
                    _LOGGER.debug('Did not get any info from the pod')
                else:
                    person_data = edges[0]['person']
                    server.member_db.set_data(member_id, person_data)

                    server.member_db.kvcache.set(
                        person_data['email'], str(member_id)
                    )
            else:
                _LOGGER.debug(
                    f'GraphQL person query failed against member {member_id}'
                )
        except (HTTPError, RequestConnectionError) as exc:
            _LOGGER.debug(f'Failed to connect to {url}: {exc}')
            continue
        #
        # and now we wait for the time to process the next client
        #
        _LOGGER.debug('Sleeping for %d seconds', waittime)
        await asyncio.sleep(waittime)


def next_member_wait(last_seen: datetime) -> int:
    '''
    Calculate how long to wait before processing the next member
    in the list. We calculate using the last_seen time of the
    current member, knowing that it is always less than the wait
    time of the next member. So we're okay with processing the
    next member to early.
    '''

    now = datetime.now(timezone.utc)

    waittime = last_seen + timedelta(seconds=MEMBER_PROCESS_INTERVAL) - now

    if waittime.seconds < 0:
        waittime.seconds = 0

    wait = min(waittime.seconds, MAX_WAIT)

    return wait


if __name__ == '__main__':
    asyncio.run(main())
