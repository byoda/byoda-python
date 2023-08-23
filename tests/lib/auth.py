'''
helper functions for authentication test cases

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import os
import shutil
import requests
from uuid import UUID

from byoda.datatypes import IdType

from byoda.datamodel.account import Account
from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.member_data_secret import MemberDataSecret
from byoda.requestauth.jwt import JWT

from byoda import config

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID


def get_jwt_header(base_url: str = BASE_URL, id: UUID = None,
                   secret: str = None,
                   service_id: int = ADDRESSBOOK_SERVICE_ID):

    if not id:
        account = config.server.account
        id = account.account_id

    if not secret:
        secret = os.environ['ACCOUNT_SECRET']

    url = base_url + '/v1/pod/authtoken'

    data = {
        'username': str(id)[:8],
        'password': secret,
    }
    if service_id is not None:
        data['service_id'] = service_id
        data['target_type'] = IdType.MEMBER.value
    else:
        data['target_type'] = IdType.ACCOUNT.value

    response = requests.post(url, json=data)

    result = response.json()

    auth_header = {
        'Authorization': f'bearer {result["auth_token"]}'
    }

    return auth_header


async def get_member_auth_header(service_id=ADDRESSBOOK_SERVICE_ID) -> str:
    account: Account = config.server.account
    await account.load_memberships()
    member = account.memberships.get(service_id)

    password = os.environ['ACCOUNT_SECRET']

    data = {
        'username': str(member.member_id)[:8],
        'password': password,
        'target_type': IdType.MEMBER.value,
        'service_id': ADDRESSBOOK_SERVICE_ID
    }
    url = f'{BASE_URL}/v1/pod/authtoken'.format(PORT=config.server.HTTP_PORT)
    response = requests.post(url, json=data)

    result = response.json()
    auth_header = {
        'Authorization': f'bearer {result["auth_token"]}'
    }
    return auth_header


async def get_azure_pod_jwt(account: Account, test_dir: str
                            ) -> tuple[str, str]:
    '''
    Gets a JWT as would be created by the Azure Pod.

    :returns: authorization header, fqdn of the Azure pod
    '''

    account = config.server.account
    member_dir = account.paths.member_directory(ADDRESSBOOK_SERVICE_ID)
    dest_dir = f'{test_dir}/{member_dir}'

    shutil.copy(
        'tests/collateral/local/azure-pod-member-data-cert.pem',
        dest_dir
    )
    shutil.copy(
        'tests/collateral/local/azure-pod-member-data.key',
        dest_dir
    )
    data_secret = MemberDataSecret(
        AZURE_POD_MEMBER_ID, ADDRESSBOOK_SERVICE_ID, account
    )
    data_secret.cert_file = f'{member_dir}/azure-pod-member-data-cert.pem'
    data_secret.private_key_file = f'{member_dir}/azure-pod-member-data.key'
    await data_secret.load()
    jwt = JWT.create(
        AZURE_POD_MEMBER_ID, IdType.MEMBER, data_secret, account.network.name,
        service_id=ADDRESSBOOK_SERVICE_ID,
        scope_type=IdType.MEMBER, scope_id=AZURE_POD_MEMBER_ID
    )
    azure_member_auth_header = {
        'Authorization': f'bearer {jwt.encoded}'
    }

    shutil.copy(
        'tests/collateral/local/azure-pod-member-cert.pem',
        dest_dir
    )
    tls_secret = MemberSecret(
        AZURE_POD_MEMBER_ID, ADDRESSBOOK_SERVICE_ID, account
    )
    tls_secret.cert_file = f'{member_dir}/azure-pod-member-cert.pem'
    # secret.private_key_file = f'{member_dir}/azure-pod-member-data.key'
    await tls_secret.load(with_private_key=False)

    return azure_member_auth_header, tls_secret.common_name


async def get_azure_pod_member_data_secret(test_dir: str,
                                           account: Account = None
                                           ) -> MemberDataSecret:

    if not account:
        account = config.podserver.account

    member_dir = account.paths.member_directory(ADDRESSBOOK_SERVICE_ID)
    dest_dir = f'{test_dir}/{member_dir}'

    shutil.copy(
        'tests/collateral/local/azure-pod-member-data-cert.pem',
        dest_dir
    )
    shutil.copy(
        'tests/collateral/local/azure-pod-member-data.key',
        dest_dir
    )
    secret = MemberSecret(
        AZURE_POD_MEMBER_ID, ADDRESSBOOK_SERVICE_ID, account
    )
    secret.cert_file = f'{member_dir}/azure-pod-member-cert.pem'
    secret.private_key_file = f'{member_dir}/azure-pod-member.key'
    await secret.load()
