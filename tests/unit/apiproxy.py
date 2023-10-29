#!/usr/bin/env python3

'''
Test cases for DataFilter and DataFilterSet classes

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

import os
import sys
import shutil
import unittest

from time import sleep
from uuid import uuid4
from datetime import datetime
from datetime import timezone

from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.data_proxy import DataProxy

from byoda.util.message_signature import MessageSignature

from byoda.secrets.member_data_secret import MemberDataSecret

from byoda.servers.pod_server import PodServer

from byoda.util.api_client.api_client import ApiClient
from byoda.util.logger import Logger
from byoda.util.fastapi import setup_api
from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network
from tests.lib.setup import setup_account

from tests.lib.defines import AZURE_POD_ACCOUNT_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID
from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

NETWORK: str = config.DEFAULT_NETWORK
TIMEOUT: int = 900
TEST_DIR: str = '/tmp/byoda-tests/recursive-data-proxy'

APP: FastAPI | None = None


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=True)

        config.test_case = "TEST_CLIENT"
        config.disable_pubsub = True

        server: PodServer = config.server

        local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
        account = await setup_account(
            network_data, test_dir=TEST_DIR,
            local_service_contract=local_service_contract, clean_pubsub=False
        )

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        config.trace_server: str = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        global APP
        APP = setup_api(
            'Byoda test pod', 'server for testing pod APIs',
            'v0.0.1', [
                AccountRouter, MemberRouter, AuthTokenRouter,
                AccountDataRouter
            ],
            lifespan=None, trace_server=config.trace_server,
        )

        for member in account.memberships.values():
            await member.enable_data_apis(
                APP, server.data_store, server.cache_store
            )

        shutil.copy(
            'tests/collateral/local/azure-pod-member-cert.pem',
            TEST_DIR
        )
        shutil.copy(
            'tests/collateral/local/azure-pod-member.key',
            TEST_DIR
        )
        shutil.copy(
            'tests/collateral/local/azure-pod-member-data-cert.pem',
            TEST_DIR
        )
        shutil.copy(
            'tests/collateral/local/azure-pod-member-data.key',
            TEST_DIR
        )

    @classmethod
    async def asyncTearDown(self):
        await ApiClient.close_all()

    async def test_string_filter(self):
        pod_account = config.server.account
        service_id = ADDRESSBOOK_SERVICE_ID
        account_member: Member = await pod_account.get_membership(service_id)

        #
        # Here we generate a request as coming from the Azure pod
        # to the test pod to confirm the member data secret of the
        # Azure pod can be downloaded by the test pod to verify the
        # parameters of the request
        #
        azure_account = Account(
            AZURE_POD_ACCOUNT_ID, network=pod_account.network
        )
        azure_member = Member(
            ADDRESSBOOK_SERVICE_ID, azure_account
        )
        azure_member.member_id = AZURE_POD_MEMBER_ID

        data_secret = MemberDataSecret(
            azure_member.member_id, azure_member.service_id
        )

        data_secret.cert_file = 'azure-pod-member-data-cert.pem'
        data_secret.private_key_file = 'azure-pod-member-data.key'
        with open('tests/collateral/local/azure-pod-private-key-password'
                  ) as file_desc:
            private_key_password = file_desc.read().strip()

        await data_secret.load(
            with_private_key=True, password=private_key_password
        )

        # Test to validate message signatures, which are used for recursive
        # queries
        plaintext = 'ik ben toch niet gek!'
        msg_sig = MessageSignature(data_secret)
        signature = msg_sig.sign_message(plaintext)
        msg_sig.verify_message(plaintext)
        signature = data_secret.sign_message(plaintext)
        data_secret.verify_message_signature(plaintext, signature)

        azure_member.schema = account_member.schema
        data_proxy = DataProxy(azure_member)
        relations = ['friend']
        filters = None
        timestamp = datetime.now(timezone.utc)
        origin_member_id = AZURE_POD_MEMBER_ID

        origin_signature = data_proxy.create_signature(
            ADDRESSBOOK_SERVICE_ID, relations, filters, timestamp,
            origin_member_id, member_data_secret=data_secret
        )

        await data_proxy.verify_signature(
            ADDRESSBOOK_SERVICE_ID, relations, filters, timestamp,
            origin_member_id, origin_signature, 1
        )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
