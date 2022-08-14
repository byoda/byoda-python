'''
helper functions for authentication test cases

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import os
import shutil
import requests
from uuid import UUID

from byoda.datatypes import IdType

from byoda.datamodel.account import Account
from byoda.secrets.member_secret import MemberSecret
from byoda.requestauth.jwt import JWT

from byoda import config

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID


def get_jwt_header(base_url: str = BASE_URL, id: UUID = None,
                   secret: str = None, member_token: bool = True):

    if not id:
        account = config.server.account
        id = account.account_id

    if not secret:
        secret = os.environ['ACCOUNT_SECRET']

    url = base_url + '/v1/pod/authtoken'

    data = {
        'account': str(id)[:8],
        'password': secret
    }
    if member_token:
        data['service_id'] = ADDRESSBOOK_SERVICE_ID

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
        'tests/collateral/local/azure-pod-member-cert.pem',
        dest_dir
    )
    shutil.copy(
        'tests/collateral/local/azure-pod-member.key',
        dest_dir
    )
    secret = MemberSecret(
        AZURE_POD_MEMBER_ID, ADDRESSBOOK_SERVICE_ID, account
    )
    secret.cert_file = f'{member_dir}/azure-pod-member-cert.pem'
    secret.private_key_file = f'{member_dir}/azure-pod-member.key'
    await secret.load()
    jwt = JWT.create(
        AZURE_POD_MEMBER_ID, IdType.MEMBER, secret, account.network.name,
        service_id=ADDRESSBOOK_SERVICE_ID
    )
    azure_member_auth_header = {
        'Authorization': f'bearer {jwt.encoded}'
    }
    return azure_member_auth_header, secret.common_name
