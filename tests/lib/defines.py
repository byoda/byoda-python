'''
Static variable definitions used in various test cases

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

from uuid import UUID

COLLATERAL_DIR = 'tests/collateral'

BASE_URL = 'http://localhost:{PORT}/api'
# FastAPI has bug where websocket app needs to be under same path as the
# HTTP app
BASE_WS_URL = 'ws://localhost:{PORT}/api'

ADDRESSBOOK_SERVICE_ID = 4294929430
ADDRESSBOOK_VERSION = 1

# Test moderation API server
MODTEST_REQUEST_URL: str = 'https://modtest.byoda.io/api/v1/moderate/asset'
moderate_claim_url: str = 'https://modtest.byoda.io/claims/{asset_id}.json'
MODTEST_API_ID: UUID = UUID('3eb0f7e5-c1e1-49b4-9633-6a6aa2a9fa22')

AZURE_POD_ACCOUNT_ID = '6e31dd43-fc13-426f-a689-a401915c29cd'
AZURE_POD_MEMBER_ID = '94f23c4b-1721-4ffe-bfed-90f86d07611a'
AZURE_POD_MEMBER_FQDN = f'{AZURE_POD_MEMBER_ID}.members-{ADDRESSBOOK_SERVICE_ID}.byoda.net'     # noqa: E501
AZURE_POD_CUSTOM_DOMAIN = 'azure.byoda.me'
AZURE_POD_SECRET_FILE = \
    'tests/collateral/local/azure-pod-account-secret.passwd'
AZURE_RESTRICTED_BUCKET_FILE = 'tests/collateral/local/restricted-storage-azure'     # noqa: E501

GCP_POD_ACCOUNT_ID = '55e43ddf-5bb8-4ba3-8dc4-82a663f55e4e'
GCP_POD_MEMBER_ID = '4e72517d-c205-4cc3-9cd7-e892a93f788a'
GCP_POD_MEMBER_FQDN = f'{GCP_POD_MEMBER_ID}.members-{ADDRESSBOOK_SERVICE_ID}.byoda.net'     # noqa: E501
GCP_POD_CUSTOM_DOMAIN = 'gcp.byoda.me'
GCP_RESTRICTED_BUCKET_FILE = 'tests/collateral/local/restricted-storage-gcp'

AWS_POD_ACCOUNT_ID = '1be0bc85-534a-40fc-8427-973603b7bf08'
AWS_POD_MEMBER_ID = 'e0f4c943-72cc-4ba9-ad9d-cd2f2c2fe6f7'
AWS_POD_MEMBER_FQDN = f'{AWS_POD_MEMBER_ID}.members-{ADDRESSBOOK_SERVICE_ID}.byoda.net'     # noqa: E501
AWS_POD_CUSTOM_DOMAIN = 'aws.byoda.me'
AWS_RESTRICTED_BUCKET_FILE = 'tests/collateral/local/restricted-storage-aws'

HOME_POD_ACCOUNT_ID = '1dbe1eb8-0421-424f-b5bf-411265630ad4'
HOME_POD_MEMBER_ID = 'b06e1928-57ef-4e22-a022-7c82be091674'
HOME_POD_MEMBER_FQDN = f'{HOME_POD_MEMBER_ID}.members-{ADDRESSBOOK_SERVICE_ID}.byoda.net'     # noqa: E501
HOME_POD_CUSTOM_DOMAIN = 'home.byoda.me'
