'''
Helper functions for tests

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license
'''

from uuid import UUID
from uuid import uuid4

from fastapi import FastAPI

from byoda.datamodel.network import Network
from byoda.datamodel.member import Member

from byoda.datatypes import DataRequestType
from byoda.datatypes import DataFilterType

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse


def get_test_uuid() -> UUID:
    id = str(uuid4())
    id: str = 'aaaaaaaa' + id[8:]
    id = UUID(id)
    return id


def get_account_tls_headers(account_id: UUID, network: str) -> dict:
    account_headers: dict[str, str] = {
        'X-Client-SSL-Verify': 'SUCCESS',
        'X-Client-SSL-Subject':
            f'CN={account_id}.accounts.{network}',
        'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network}'
    }
    return account_headers


def get_member_tls_headers(member_id: UUID, network: str | Network,
                           service_id: int) -> dict:
    if isinstance(network, Network):
        network = network.name

    member_headers: dict[str, str] = {
        'X-Client-SSL-Verify': 'SUCCESS',
        'X-Client-SSL-Subject':
            f'CN={member_id}.members-{service_id}.{network}',
        'X-Client-SSL-Issuing-CA': f'CN=members-ca.{network}'
    }
    return member_headers


async def call_data_api(service_id: int, class_name: str,
                        action: DataRequestType = DataRequestType.QUERY,
                        first: int | None = None, after: str | None = None,
                        depth: int = 0, fields: set[str] | None = None,
                        data_filter: DataFilterType | None = None,
                        data: dict[str, object] | None = None,
                        auth_header: str = None, expect_success: bool = True,
                        app: FastAPI = None, test=None, internal: bool = True,
                        member: Member | None = None
                        ) -> dict[str, object] | int | None:
    '''
    Wrapper for REST Data API for test cases

    :param service_id:
    :param class_name:
    :param action:
    :param first:
    :param after:
    :param depth:
    :param fields:
    :param data_filter:
    :param data:
    :param auth_header:
    :param expect_success: should the HTTP status code match '200'
    :param test: unittest.TestCase
    :returns:
    :raises:
    '''

    member_id: UUID | None = None
    if member:
        member_id = member.member_id

    resp: HttpResponse = await DataApiClient.call(
        service_id=service_id, class_name=class_name, action=action,
        first=first, after=after, depth=depth, fields=fields,
        data_filter=data_filter, data=data, member_id=member_id,
        headers=auth_header, app=app, internal=internal
    )

    if test and expect_success:
        test.assertEqual(resp.status_code, 200)

    result: dict = resp.json()

    if not expect_success or not test:
        return result

    if action == DataRequestType.QUERY:
        test.assertIsNotNone(result['total_count'])
    elif action in (DataRequestType.APPEND, DataRequestType.DELETE):
        test.assertIsNotNone(result)
        test.assertGreater(result, 0)
    else:
        pass

    return result
