'''
Helper functions to set up tests

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import os
import shutil

from byoda import config

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account

from byoda.servers.pod_server import PodServer

from byoda.datastore.document_store import DocumentStoreType
from byoda.datatypes import CloudType

from podserver.util import get_environment_vars

from tests.lib.util import get_test_uuid


async def setup_network(test_dir: str) -> dict[str, str]:
    config.debug = True

    if test_dir:
        try:
            shutil.rmtree(test_dir)
        except FileNotFoundError:
            pass

        os.makedirs(test_dir)
    else:
        test_dir = '/tmp'

    shutil.copy('tests/collateral/addressbook.json', test_dir)

    os.environ['ROOT_DIR'] = test_dir
    os.environ['BUCKET_PREFIX'] = 'byoda'
    os.environ['CLOUD'] = 'LOCAL'
    os.environ['NETWORK'] = 'byoda.net'
    os.environ['ACCOUNT_ID'] = str(get_test_uuid())
    os.environ['ACCOUNT_SECRET'] = 'test'
    os.environ['LOGLEVEL'] = 'DEBUG'
    os.environ['PRIVATE_KEY_SECRET'] = 'byoda'
    os.environ['BOOTSTRAP'] = 'BOOTSTRAP'

    network_data = get_environment_vars()

    network = Network(network_data, network_data)
    await network.load_network_secrets()

    config.test_case = True

    config.server = PodServer(network)
    config.server.network = network

    await config.server.set_document_store(
        DocumentStoreType.SQLITE, root_dir=network_data['root_dir']
    )

    config.server.paths = network.paths

    return network_data


async def setup_account(network_data: dict[str, str]) -> Account:
    server = config.server
    await server.set_document_store(
        DocumentStoreType.SQLITE, root_dir=network_data['root_dir']
    )

    pod_account = Account(network_data['account_id'], server.network)
    await pod_account.paths.create_account_directory()
    await pod_account.load_memberships()

    server.account = pod_account

    pod_account.password = os.environ['ACCOUNT_SECRET']

    await pod_account.create_account_secret()
    await pod_account.create_data_secret()
    await pod_account.register()

    await server.get_registered_services()

    services = list(server.network.service_summaries.values())
    service = [
        service
        for service in services
        if service['name'] == 'addressbook'
    ][0]

    global ADDRESSBOOK_SERVICE_ID
    ADDRESSBOOK_SERVICE_ID = service['service_id']
    global ADDRESSBOOK_VERSION
    ADDRESSBOOK_VERSION = service['version']

    member_id = get_test_uuid()
    await pod_account.join(
        ADDRESSBOOK_SERVICE_ID, ADDRESSBOOK_VERSION, member_id=member_id,
        local_service_contract='addressbook.json'
    )

    return pod_account
