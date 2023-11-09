'''
Test cases for byoda.util.updates_listener class and classes derived
from it

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

import os
import sys
import yaml
import shutil
import unittest

from uuid import UUID
from datetime import datetime
from datetime import timezone

from anyio import create_task_group
from anyio import sleep

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account
from byoda.datamodel.service import Service
from byoda.datamodel.member import Member
from byoda.datamodel.schema import Schema

from byoda.datatypes import DataRequestType

from byoda.storage.filestorage import FileStorage
from byoda.datatypes import CloudType

from byoda.datastore.document_store import DocumentStoreType, DocumentStore

from byoda.servers.service_server import ServiceServer

from byoda.util.updates_listener import UpdateListenerService

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse
from byoda.util.logger import Logger

from byoda.util.paths import Paths

from byoda import config

from tests.lib.setup import get_test_uuid

from tests.lib.auth import get_azure_pod_jwt

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import AZURE_POD_ACCOUNT_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID

from podserver.codegen.pydantic_service_4294929430_1 import (
    asset as Asset,
    video_chapter as Video_chapter,
    video_thumbnail as Video_thumbnail,
    claim as Claim,
    monetization as Monetization
)

TEST_DIR = '/tmp/byoda-tests/assetdb'

TEST_ASSET_ID: UUID = '32af2122-4bab-40bb-99cb-4f696da49e26'

DUMMY_SCHEMA = 'tests/collateral/addressbook.json'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        config.test_case = 'TEST_CLIENT'

        os.makedirs(TEST_DIR)

    @classmethod
    async def asyncTearDown(self):
        await ApiClient.close_all()

    async def test_service(self):
        config_file = os.environ.get('CONFIG_FILE', 'config.yml')
        with open(config_file) as file_desc:
            app_config = yaml.safe_load(file_desc)

        app_config['svcserver']['root_dir'] = TEST_DIR

        network = Network(
            app_config['svcserver'], app_config['application']
        )

        network.paths = Paths(
            network=network.name,
            root_directory=app_config['svcserver']['root_dir']
        )

        service_file = network.paths.get(
            Paths.SERVICE_FILE, service_id=ADDRESSBOOK_SERVICE_ID
        )

        server = await ServiceServer.setup(network, app_config)
        storage = FileStorage(app_config['svcserver']['root_dir'])
        await server.load_network_secrets(storage_driver=storage)

        shutil.copytree(
            'tests/collateral/local/addressbook-service/service-4294929430',
            f'{TEST_DIR}/network-byoda.net/services/service-4294929430'
        )
        shutil.copytree(
            'tests/collateral/local/addressbook-service/private/',
            f'{TEST_DIR}/private'
        )

        service_dir: str = TEST_DIR + '/' + service_file
        shutil.copy(DUMMY_SCHEMA, service_dir)

        await server.load_secrets(
            password=app_config['svcserver']['private_key_password']
        )
        config.server = server

        await server.service.examine_servicecontract(service_file)
        server.service.name = 'addressbook'

        service: Service = server.service
        service.tls_secret.save_tmp_private_key()

        if not await service.paths.service_file_exists(service.service_id):
            await service.download_schema(save=True)

        await server.load_schema(verify_contract_signatures=False)
        schema: Schema = service.schema
        schema.get_data_classes(with_pubsub=False)
        schema.generate_data_models('svcserver/codegen', datamodels_only=True)

        await server.setup_asset_cache(app_config['svcserver']['cache'])

        config.trace_server: str = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        #
        # Set up the listener
        #
        class_name: str = 'public_assets'
        test_list: str = 'test_case_updates_listener'
        member_id: UUID = UUID(AZURE_POD_MEMBER_ID)
        listener = await UpdateListenerService.setup(
            class_name, service.service_id, member_id,
            service.network.name, service.tls_secret,
            server.asset_cache, [test_list]
        )

        item_count = await listener.get_all_data()
        self.assertGreater(item_count, 1)

        #
        # Prep Account object for Azure pod so that we can
        # call the Azure pod with its own JWT
        #
        account = Account(AZURE_POD_ACCOUNT_ID, network)
        config.server.account = account
        config.server.data_store = None
        config.server.cache_store = None
        account.document_store = \
            await DocumentStore.get_document_store(
                DocumentStoreType.OBJECT_STORE, cloud_type=CloudType.LOCAL,
                private_bucket='a', restricted_bucket='v',
                public_bucket='c', root_dir=TEST_DIR
            )
        member: Member = await account.join(
            service.service_id, 1,
            account.document_store.backend, service.members_ca, get_test_uuid()
        )
        await member.load_secrets()
        auth_header, _ = await get_azure_pod_jwt(account, TEST_DIR)

        #
        # Prep a test asset that we'll add to the Azure pod
        #
        asset_id = get_test_uuid()
        data: dict[str, dict] = {
            'data': {
                'asset_id': asset_id,
                'asset_type': 'test',
                'created_timestamp': datetime.now(tz=timezone.utc),
            }
        }

        #
        # Here we start with the test
        #
        async with create_task_group() as task_group:
            await listener.setup_listen_assets(task_group)
            await sleep(2)

            resp: HttpResponse = await DataApiClient.call(
                service.service_id, class_name, DataRequestType.APPEND,
                network=service.network.name, headers=auth_header,
                member_id=AZURE_POD_MEMBER_ID, data=data
            )
            self.assertEqual(resp.status_code, 200)

            await sleep(3)

            result = await listener.asset_cache.asset_exists_in_cache(
                test_list, AZURE_POD_MEMBER_ID, asset_id
            )
            self.assertTrue(result)

            #
            # Clean up
            #
            task_group.cancel_scope.cancel()

            await listener.asset_cache.delete_asset_from_cache(
                test_list, member_id, asset_id
            )
            await listener.asset_cache.delete_list(test_list)

            resp: HttpResponse = await DataApiClient.call(
                service.service_id, class_name, DataRequestType.DELETE,
                network=service.network.name, headers=auth_header,
                member_id=AZURE_POD_MEMBER_ID,
                data_filter={'asset_id': {'eq': asset_id}}
            )
            self.assertEqual(resp.status_code, 200)


def get_asset(asset_id: str = TEST_ASSET_ID) -> dict[str, object]:
    '''
    Creates and returns an asset object with dummy data.
    '''

    if not asset_id:
        asset_id = get_test_uuid()
    if not isinstance(asset_id, UUID):
        asset_id = UUID(asset_id)

    thumbnail_1 = Video_thumbnail(
        thumbnail_id=str(get_test_uuid()), width=640, height=480,
        size='640x480', preference='default', url='https://thumbnail_url',
    )
    thumbnail_2 = Video_thumbnail(
        thumbnail_id=str(get_test_uuid()), width=320, height=2480,
        size='320x240', preference='default', url='https://thumbnail2_url',
    )

    chapter_1 = Video_chapter(
        chapter_id=str(get_test_uuid()), start=0.0, end=10.0, title='chapter',
    )

    chapter_2 = Video_chapter(
        chapter_id=str(get_test_uuid()), start=0.0, end=10.0, title='chapter',
    )

    claim_1 = Claim(
        claim_id=str(get_test_uuid()),
        cert_expiration=datetime.now(tz=timezone.utc).isoformat(),
        cert_fingerprint='claim1_fingerprint',
        issuer_id=str(get_test_uuid()),
        issuer_type='app', keyfield='asset_id',
        requester_id=str(get_test_uuid()), requester_type='member',
        keyfield_id=str(asset_id),
        object_fields=['blah1', 'blah12'], object_type='public_assets',
        signature='blah', signature_format_version=1,
        signature_timestamp=datetime.now(tz=timezone.utc).isoformat(),
        signature_url='https://signature_url',
        renewal_url='https://renewal_url',
        confirmation_url='https://confirmation_url',
        claims=['claim11', 'claim12', 'claim13']
    )

    claim_2 = Claim(
        claim_id=str(get_test_uuid()),
        cert_expiration=datetime.now(tz=timezone.utc).isoformat(),
        cert_fingerprint='claim2_fingerprint',
        issuer_id=str(get_test_uuid()),
        issuer_type='app', keyfield='asset_id',
        keyfield_id=str(asset_id),
        object_fields=['blah2', 'blah22'], object_type='public_assets',
        requester_id=str(get_test_uuid()), requester_type='member',
        signature='blah', signature_format_version=1,
        signature_timestamp=datetime.now(tz=timezone.utc).isoformat(),
        signature_url='https://signature2_url',
        renewal_url='https://renewal2_url',
        confirmation_url='https://confirmation2_url',
        claims=['claim21', 'claim22', 'claim23']
    )

    monetization_1 = Monetization(
        monetization_id=str(get_test_uuid()),
        monetization_scheme='free'
    )

    asset = Asset(
        asset_id=asset_id, asset_type='video',
        created_timestamp=datetime.now(tz=timezone.utc),
        asset_merkle_root_hash='1',
        asset_url='https://asset_url',
        channel_id=get_test_uuid(),
        content_warnings=['warning1', 'warning2'],
        contents='contents',
        copyright_years=[102, 1492],
        creator='byoda',
        ingest_status='published',
        published_timestamp=datetime.now(tz=timezone.utc),
        publisher='byoda',
        publisher_asset_id='byoda',
        screen_orientation_horizontal=True,
        title='asset', subject='asset',
        video_thumbnails=[thumbnail_1, thumbnail_2],
        video_chapters=[chapter_1, chapter_2],
        claims=[claim_1, claim_2],
        monetizations=[monetization_1]
    )
    return asset


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
