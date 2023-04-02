'''
Static variable definitions used in various test cases

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

BASE_URL = 'http://localhost:{PORT}/api'
# FastAPI has bug where websocket app needs to be under same path as the
# HTTP app
BASE_WS_URL = 'ws://localhost:{PORT}/api'

ADDRESSBOOK_SERVICE_ID = 4294929430
ADDRESSBOOK_VERSION = 1


AZURE_POD_ACCOUNT_ID = '6e31dd43-fc13-426f-a689-a401915c29cd'
AZURE_POD_MEMBER_ID = '3d0fff6a-b043-430e-afb3-0e2995b69da5'
AZURE_POD_CUSTOM_DOMAIN = 'azure.byoda.me'
AZURE_POD_SECRET_FILE = \
    'tests/collateral/local/azure-pod-account-secret.passwd'

GCP_POD_ACCOUNT_ID = '55e43ddf-5bb8-4ba3-8dc4-82a663f55e4e'
GCP_POD_MEMBER_ID = '16557707-37f1-4582-b2ee-4fad2e811e3f'
GCP_POD_CUSTOM_DOMAIN = 'gcp.byoda.me'

AWS_POD_ACCOUNT_ID = '1be0bc85-534a-40fc-8427-973603b7bf08'
AWS_POD_MEMBER_ID = '65f0063e-145c-4c2a-859f-767e251f693c'
AWS_POD_CUSTOM_DOMAIN = 'aws.byoda.me'

HOME_POD_ACCOUNT_ID = '1dbe1eb8-0421-424f-b5bf-411265630ad4'
HOME_POD_MEMBER_ID = '8fe9c737-7715-40f2-8d6a-da743fda6ce2'
HOME_POD_CUSTOM_DOMAIN = 'home.byoda.me'
