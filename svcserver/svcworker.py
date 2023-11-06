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

from uuid import UUID
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import orjson

from anyio import run
from anyio import sleep
from anyio import create_task_group
from anyio.abc import TaskGroup

from httpx import ConnectError
from httpx import HTTPError

from byoda.datamodel.service import Service
from byoda.datamodel.network import Network

from byoda.datatypes import DataRequestType

from byoda.datastore.memberdb import MemberDb

from byoda.datacache.assetcache import AssetCache

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
    service, server = await setup_server()

    _LOGGER.debug(
        f'Starting service worker for service ID: {service.service_id}'
    )

    member_db: MemberDb = server.member_db
    waittime: float = 0.0
    members_seen: dict[str, UUID] = {}

    async with create_task_group() as task_group:
        while True:
            _LOGGER.debug('Sleeping for %d seconds', waittime)
            await sleep(waittime)
            waittime = 0.1

            member_id: UUID = await member_db.get_next(timeout=MAX_WAIT)
            if not member_id:
                _LOGGER.debug('No member available in list of members')
                continue

            if str(member_id).startswith('aaaaaaaa'):
                _LOGGER.debug(
                    f'Not processing member with test UUID: {member_id}'
                )
                continue

            _LOGGER.debug(f'Processing member_id {member_id}')

            if member_id not in members_seen:
                await setup_listen(task_group, member_id, service, member_db)
                members_seen[member_id] = member_id

            waittime: int = await update_member(
                service, member_id, server.member_db
            )

            if not waittime:
                waittime = 0.1
            else:
                # Add the member back to the list of members as it seems
                # to be up and running, even if it may not have returned
                # any data
                await member_db.add_member(member_id)

            #
            # and now we wait for the time to process the next client
            #


async def setup_listen(task_group: TaskGroup, member_id: UUID,
                       service: Service, asset_cache: AssetCache) -> None:
    '''
    Initiates listening for updates to the 'public_assets' table of
    the member.

    :param task_group:
    :param member_id: the target member
    :param service: our own service
    :asset_db:
    :returns: (none)
    :raises:
    '''

    pass


async def update_member(service: Service, member_id: UUID, member_db: MemberDb
                        ) -> int | None:
    '''
    '''

    try:
        data = await member_db.get_meta(member_id)
    except TypeError as exc:
        _LOGGER.exception(f'Invalid data for member: {member_id}: {exc}')
        return None
    except KeyError as exc:
        _LOGGER.info(f'Member not found: {member_id}: {exc}')
        return None

    await member_db.add_meta(
        data['member_id'], data['remote_addr'], data['schema_version'],
        data['data_secret'], data['status']
    )

    waittime = next_member_wait(data['last_seen'])

    #
    # Here is where we can do stuff
    #
    try:
        await update_member_info(service, member_db, member_id)

    except (HTTPError, ConnectError, ByodaRuntimeError) as exc:
        _LOGGER.info(
            f'Not adding member back to the list because we failed '
            f'to get data from member: {member_id}: {exc}'
        )
        return None

    return waittime


async def update_member_info(service: Service, member_db: MemberDb,
                             member_id: UUID) -> None:
    '''
    Updates the info about a member of the service so that we
    can support searches based on email address of the member

    :param service: our service
    :param meber_db: where to store the data
    :param member_id: the member to update
    :returns: (none)
    :raises: (none)
    '''

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
        await member_db.set_data(member_id, person_data)

        await member_db.kvcache.set(
            person_data['email'], str(member_id)
        )


def next_member_wait(last_seen: datetime) -> int:
    '''
    Calculate how long to wait before processing the next member
    in the list. We calculate using the last_seen time of the
    current member, knowing that it is always less than the wait
    time of the next member. So we're okay with processing the
    next member to early.

    :param last_seen: The last time the member was seen
    :return: number of seconds to sleep
    :raises: (none)
    '''

    now = datetime.now(timezone.utc)

    waittime = last_seen + timedelta(seconds=MEMBER_PROCESS_INTERVAL) - now

    if waittime.seconds < 0:
        waittime.seconds = 0

    wait = min(waittime.seconds, MAX_WAIT)

    return wait


async def setup_server() -> (Service, ServiceServer):
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
    server = await ServiceServer.setup(network, app_config)
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

    return service, server


if __name__ == '__main__':
    run(main)
