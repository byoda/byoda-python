'''
helper functions for authentication test cases

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license
'''

import os
import shutil

from uuid import UUID

from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.datatypes import IdType

from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.member_data_secret import MemberDataSecret

from byoda.requestauth.jwt import JWT

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse
from byoda.util.api_client.restapi_client import HttpMethod

from byoda.servers.pod_server import PodServer

from byoda import config

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import BYOTUBE_SERVICE_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID


def get_jwt_header(base_url: str = BASE_URL, id: UUID = None,
                   secret: str = None,
                   service_id: int = ADDRESSBOOK_SERVICE_ID,
                   app: FastAPI | None = None) -> dict[str, str]:

    if not id:
        account: Account = config.server.account
        id = account.account_id

    if not secret:
        secret = os.environ['ACCOUNT_SECRET']

    url: str = base_url + '/v1/pod/authtoken'

    data: dict[str, str] = {
        'username': str(id)[:8],
        'password': secret,
    }
    if service_id is not None:
        data['service_id'] = service_id
        data['target_type'] = IdType.MEMBER.value
    else:
        data['target_type'] = IdType.ACCOUNT.value

    # resp: HttpResponse = httpx.post(url, json=data)
    resp: HttpResponse = ApiClient.call_sync(
        url, method=HttpMethod.POST, data=data, app=app
    )
    result: dict[str, any] = resp.json()

    auth_header: dict[str, str] = {
        'Authorization': f'bearer {result["auth_token"]}'
    }

    return auth_header


async def get_member_auth_header(service_id=ADDRESSBOOK_SERVICE_ID,
                                 app: FastAPI | None = None, test=None
                                 ) -> str:
    server: PodServer = config.server
    account: Account = server.account
    member: Member = await account.get_membership(service_id)

    password: str = os.environ['ACCOUNT_SECRET']

    data: dict[str, str | int] = {
        'username': str(member.member_id)[:8],
        'password': password,
        'target_type': IdType.MEMBER.value,
        'service_id': service_id
    }
    url: str = f'{BASE_URL}/v1/pod/authtoken'.format(
        PORT=config.server.HTTP_PORT
    )
    response: HttpResponse = await ApiClient.call(
        url, method=HttpMethod.POST, data=data, app=app, timeout=600
    )

    if test:
        test.assertEqual(response.status_code, 200)

    result: dict[str, str] = response.json()

    if test:
        test.assertIsNotNone(result.get('auth_token'))

    auth_header: dict[str, str] = {
        'Authorization': f'bearer {result["auth_token"]}'
    }
    return auth_header


async def get_azure_pod_jwt(account: Account, test_dir: str,
                            service_id: int =
                            ADDRESSBOOK_SERVICE_ID) -> tuple[str, str]:
    '''
    Gets a JWT as would be created by the Azure Pod.

    :returns: authorization header, fqdn of the Azure pod
    '''

    member_dir: str = account.paths.member_directory(service_id)
    dest_dir: str = f'{test_dir}/{member_dir}'

    shutil.copy(
        'tests/collateral/local/azure-pod-member-data-cert.pem',
        dest_dir
    )
    shutil.copy(
        'tests/collateral/local/azure-pod-member-data.key',
        dest_dir
    )
    data_secret = MemberDataSecret(
        AZURE_POD_MEMBER_ID, service_id, account
    )
    data_secret.cert_file = f'{member_dir}/azure-pod-member-data-cert.pem'
    data_secret.private_key_file = f'{member_dir}/azure-pod-member-data.key'
    await data_secret.load()
    jwt = JWT.create(
        AZURE_POD_MEMBER_ID, IdType.MEMBER, data_secret, account.network.name,
        service_id=service_id, scope_type=IdType.MEMBER,
        scope_id=AZURE_POD_MEMBER_ID
    )
    azure_member_auth_header: dict[str, str] = {
        'Authorization': f'bearer {jwt.encoded}'
    }

    shutil.copy(
        'tests/collateral/local/azure-pod-member-cert.pem',
        dest_dir
    )
    tls_secret = MemberSecret(
        AZURE_POD_MEMBER_ID, service_id, account
    )
    tls_secret.cert_file = f'{member_dir}/azure-pod-member-cert.pem'
    # secret.private_key_file = f'{member_dir}/azure-pod-member-data.key'
    await tls_secret.load(with_private_key=False)

    return azure_member_auth_header, tls_secret.common_name


async def get_pod_jwt(account: Account, pod_hostname: str, test_dir: str,
                      member_id: UUID, service_id: int = BYOTUBE_SERVICE_ID
                      ) -> tuple[str, str]:
    '''
    Gets a JWT as would be created by the Azure Pod.

    :returns: authorization header, fqdn of the pod
    '''

    member_dir: str = account.paths.member_directory(service_id)
    dest_dir: str = f'{test_dir}/{member_dir}'

    shutil.copy(
        f'tests/collateral/local/{pod_hostname}-pod-member-data-cert.pem',
        dest_dir
    )
    shutil.copy(
        f'tests/collateral/local/{pod_hostname}-pod-member-data.key',
        dest_dir
    )
    passphrase_file: str = \
        f'tests/collateral/local/{pod_hostname}-pod-key.secret'
    with open(passphrase_file, 'r') as file_disc:
        passphrase: str = file_disc.read().strip()

    data_secret = MemberDataSecret(
        AZURE_POD_MEMBER_ID, service_id, account
    )
    data_secret.cert_file = \
        f'{member_dir}/{pod_hostname}-pod-member-data-cert.pem'
    data_secret.private_key_file = \
        f'{member_dir}/{pod_hostname}-pod-member-data.key'
    await data_secret.load(password=passphrase)
    jwt: JWT = JWT.create(
        member_id, IdType.MEMBER, data_secret, account.network.name,
        service_id=service_id, scope_type=IdType.MEMBER,
        scope_id=member_id
    )
    pod_member_auth_header: dict[str, str] = {
        'Authorization': f'bearer {jwt.encoded}'
    }

    shutil.copy(
        f'tests/collateral/local/{pod_hostname}-pod-member-cert.pem',
        dest_dir
    )
    tls_secret = MemberSecret(
        member_id, service_id, account
    )
    tls_secret.cert_file = f'{member_dir}/{pod_hostname}-pod-member-cert.pem'
    # secret.private_key_file = \
    #   f'{member_dir}/{pod_hostname}-pod-member-data.key'
    await tls_secret.load(with_private_key=False)

    return pod_member_auth_header, tls_secret.common_name


async def get_azure_pod_member_data_secret(test_dir: str,
                                           account: Account = None
                                           ) -> MemberDataSecret:

    if not account:
        account = config.podserver.account

    member_dir: str = account.paths.member_directory(ADDRESSBOOK_SERVICE_ID)
    dest_dir: str = f'{test_dir}/{member_dir}'

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
