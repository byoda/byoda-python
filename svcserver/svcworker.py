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

from datetime import datetime, timedelta, timezone

import orjson

from requests.exceptions import ConnectionError as RequestConnectionError
from requests.exceptions import HTTPError

from byoda.datamodel.service import Service
from byoda.datamodel.network import Network

from byoda.datatypes import DataRequestType

from byoda.datastore.memberdb import MemberDb

from byoda.storage.filestorage import FileStorage

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.paths import Paths

from byoda.servers.service_server import ServiceServer

from byoda.exceptions import ByodaRuntimeError

from byoda.util.logger import Logger

from byoda import config


MAX_WAIT = 15 * 60
MEMBER_PROCESS_INTERVAL = 8 * 60 * 60


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
    storage = FileStorage(app_config['svcserver']['root_dir'])
    await server.load_network_secrets(storage_driver=storage)

    await server.load_secrets(
        password=app_config['svcserver']['private_key_password']
    )
    config.server = server

    service: Service = server.service
    service.tls_secret.save_tmp_private_key()

    if not await service.paths.service_file_exists(service.service_id):
        await service.download_schema(save=True)

    await server.load_schema(verify_contract_signatures=False)

    _LOGGER.debug(
        f'Starting service worker for service ID: {service.service_id}'
    )

    member_db: MemberDb = server.member_db
    while True:
        member_id = member_db.get_next(timeout=MAX_WAIT)

        if not member_id:
            _LOGGER.debug('No member available in list of members')
            continue

        if str(member_id).startswith('aaaaaaaa'):
            _LOGGER.debug(
                f'Not processing member with test UUID: {member_id}'
            )
            continue

        _LOGGER.debug(f'Processing member_id {member_id}')
        try:
            data = member_db.get_meta(member_id)
        except TypeError as exc:
            _LOGGER.exception(f'Invalid data for member: {member_id}: {exc}')
            continue
        except KeyError as exc:
            _LOGGER.info(f'Member not found: {member_id}: {exc}')
            continue

        member_db.add_meta(
            data['member_id'], data['remote_addr'], data['schema_version'],
            data['data_secret'], data['status']
        )

        waittime = next_member_wait(data['last_seen'])

        #
        # Here is where we can do stuff
        #
        try:
            resp: HttpResponse = await DataApiClient.call(
                service.service_id, 'person', DataRequestType.QUERY,
                secret=service.tls_secret, member_id=member_id
            )

            body = resp.json()

            edges = body['edges']
            if not edges:
                _LOGGER.debug(f'Did not get any info from the pod: {body}')
            else:
                person_data = edges[0]['node']
                _LOGGER.info(
                    f'Got data from member {member_id}: '
                    f'{orjson.dumps(person_data)}'
                )
                member_db.set_data(member_id, person_data)

                member_db.kvcache.set(
                    person_data['email'], str(member_id)
                )

            # Add the member back to the list of members as it seems
            # to be up and running, even if it may not have returned
            # any data
            member_db.add_member(member_id)
        except (HTTPError, RequestConnectionError, ByodaRuntimeError) as exc:
            _LOGGER.info(
                f'Not adding member back to the list because we failed '
                f'to get data from member: {member_id}: {exc}'
            )
            # Safety measure that we don't have an error case where
            # we consume 100% CPU
            await asyncio.sleep(0.1)
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
