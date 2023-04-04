'''
Helper functions for tests

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

from uuid import uuid4, UUID


def get_test_uuid() -> UUID:
    id = str(uuid4())
    id = 'aaaaaaaa' + id[8:]
    id = UUID(id)
    return id


def get_account_tls_headers(account_id: UUID, network: str) -> dict:
    account_headers = {
        'X-Client-SSL-Verify': 'SUCCESS',
        'X-Client-SSL-Subject':
            f'CN={account_id}.accounts.{network}',
        'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network}'
    }
    return account_headers


def get_member_tls_headers(member_id: UUID, network: str, service_id: int) -> dict:
    member_headers = {
        'X-Client-SSL-Verify': 'SUCCESS',
        'X-Client-SSL-Subject':
            f'CN={member_id}.members-{service_id}.{network}',
        'X-Client-SSL-Issuing-CA': f'CN=members-ca.{network}'
    }
    return member_headers