# flake8: noqa: E501

'''
Static variable definitions used in various test cases

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license
'''

from uuid import UUID

COLLATERAL_DIR = 'tests/collateral'

BASE_URL: str = 'http://localhost:{PORT}/api'
DATA_API_WS_URL: str = 'ws://localhost:{PORT}/api/v1/data/{service_id}/{class_name}/{action}'

ADDRESSBOOK_SERVICE_ID: int = 4294929430
ADDRESSBOOK_VERSION: int = 1

BYOTUBE_SERVICE_ID: int = 16384
BYOTUBE_VERSION: int = 1

# Test moderation API server
MODTEST_FQDN: str = 'modtest.byoda.io'
MODTEST_APP_ID: UUID = UUID('3eb0f7e5-c1e1-49b4-9633-6a6aa2a9fa22')

CDN_APP_ID: UUID = UUID('928ef3d7-f4fd-4b41-b6c8-2bc4a201b2e8')
CDN_FQDN: str = 'cdn.byo.tube'
CDN_ORIGIN_SITE_ID: str | None = 'xx'

AZURE_POD_ACCOUNT_ID: str = '6e31dd43-fc13-426f-a689-a401915c29cd'
AZURE_POD_MEMBER_ID: str = '94f23c4b-1721-4ffe-bfed-90f86d07611a'
AZURE_POD_MEMBER_FQDN: str = f'{AZURE_POD_MEMBER_ID}.members-{ADDRESSBOOK_SERVICE_ID}.byoda.net'
AZURE_POD_CUSTOM_DOMAIN: str = 'azure.byoda.me'

AZURE_POD_ADDRESS_BOOK_PUBLIC_ASSETS_ASSET_ID: str = 'aaaaaaaa-513c-49d8-b034-c7c12b915a95'

AZURE_POD_ACCOUNT_SECRET_FILE: str = 'tests/collateral/local/azure-pod-account-secret.passwd'
AZURE_POD_MEMBER_SECRET_FILE: str = 'tests/collateral/local/azure-pod-member-secret.passwd'
AZURE_RESTRICTED_BUCKET_FILE: str = 'tests/collateral/local/restricted-storage-azure'


GCP_POD_ACCOUNT_ID: str = '55e43ddf-5bb8-4ba3-8dc4-82a663f55e4e'
GCP_POD_MEMBER_ID: str = '4e72517d-c205-4cc3-9cd7-e892a93f788a'
GCP_POD_MEMBER_FQDN: str = f'{GCP_POD_MEMBER_ID}.members-{ADDRESSBOOK_SERVICE_ID}.byoda.net'
GCP_POD_CUSTOM_DOMAIN: str = 'gcp.byoda.me'
GCP_RESTRICTED_BUCKET_FILE: str = 'tests/collateral/local/restricted-storage-gcp'

AWS_POD_ACCOUNT_ID: str = '1be0bc85-534a-40fc-8427-973603b7bf08'
AWS_POD_MEMBER_ID: str = 'e0f4c943-72cc-4ba9-ad9d-cd2f2c2fe6f7'
AWS_POD_MEMBER_FQDN: str = f'{AWS_POD_MEMBER_ID}.members-{ADDRESSBOOK_SERVICE_ID}.byoda.net'
AWS_POD_CUSTOM_DOMAIN: str = 'aws.byoda.me'
AWS_RESTRICTED_BUCKET_FILE: str = 'tests/collateral/local/restricted-storage-aws'

HOME_POD_ACCOUNT_ID: str = '1dbe1eb8-0421-424f-b5bf-411265630ad4'
HOME_POD_MEMBER_ID: str = 'b06e1928-57ef-4e22-a022-7c82be091674'
HOME_POD_MEMBER_FQDN: str = f'{HOME_POD_MEMBER_ID}.members-{ADDRESSBOOK_SERVICE_ID}.byoda.net'
HOME_POD_CUSTOM_DOMAIN: str = 'home.byoda.me'

DATHES_POD_ACCOUNT_ID: str = ''
DATHES_POD_MEMBER_ID: str = '83f94060-2648-4046-80f1-9a3eb189ca95'
DATHES_POD_MEMBER_FQDN: str = f'{DATHES_POD_MEMBER_ID}.members-{BYOTUBE_SERVICE_ID}.byoda.net'

TEST_IDS: dict[str, dict[str, str]] = {
    'azure': {
        'account_id': AZURE_POD_ACCOUNT_ID,
        'member_id': AZURE_POD_MEMBER_ID,
    },
    'home': {
        'account_id': HOME_POD_ACCOUNT_ID,
        'member_id': HOME_POD_MEMBER_ID,
    },
    'aws': {
        'account_id': AWS_POD_ACCOUNT_ID,
        'member_id': AWS_POD_MEMBER_ID,
    },
    'gcp': {
        'account_id': GCP_POD_ACCOUNT_ID,
        'member_id': GCP_POD_MEMBER_ID,
    },
}