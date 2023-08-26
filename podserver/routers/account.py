'''
/pod/account API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''


import os
import logging

from fastapi import APIRouter, Request

from byoda.datatypes import StorageType, CloudType

from byoda.models import AccountResponseModel

from byoda import config

from ..dependencies.pod_api_request_auth import AuthDep

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/pod', dependencies=[])


@router.get('/account', response_model=AccountResponseModel)
async def get_account(request: Request, auth: AuthDep):
    '''
    Get data for the pod account.
    The data request is evaluated using the identify specified in the
    client cert.
    '''

    _LOGGER.debug(f'GET Account API called from {request.client.host}')
    await auth.authenticate()

    # Authorization: handled by PodApiRequestAuth, which checks account
    # cert / JWT was used and it matches the account ID of the pod

    server = config.server
    account = server.account
    network = account.network
    doc_store = account.document_store
    if doc_store.backend.cloud_type == CloudType.LOCAL:
        private_bucket = 'LOCAL'
        restricted_bucket = '/byoda/restricted'
        public_bucket = '/byoda/public'
    else:
        private_bucket = doc_store.backend.get_url(StorageType.PRIVATE.value)
        restricted_bucket = doc_store.backend.get_url(
            StorageType.RESTRICTED.value
        )
        public_bucket = doc_store.backend.get_url(StorageType.PUBLIC.value)

    bootstrap = os.environ.get('BOOTSTRAP')
    if not bootstrap:
        bootstrap = False
    elif bootstrap.upper() in ('TRUE', 'BOOTSTRAP'):
        bootstrap = True
    else:
        bootstrap = False

    root_directory = account.paths.root_directory

    await account.load_memberships()

    services = []
    for service in network.service_summaries.values():
        service_id = service['service_id']
        if service_id in account.memberships:
            member = account.memberships[service_id]
            joined = True
            join_version = member.schema.version
        else:
            joined = False
            join_version = None

        services.append(
            {
                'service_id': service_id,
                'name': service['name'],
                'latest_contract_version': service['version'],
                'member': joined,
                'accepted_contract_version': join_version
            }
        )

    data = {
        "account_id": server.account.account_id,
        "network": server.network.name,
        "started": server.started,
        "cloud": doc_store.backend.cloud_type,
        "private_bucket": private_bucket,
        "restricted_bucket": restricted_bucket,
        "public_bucket": public_bucket,
        "loglevel": os.environ.get('LOGLEVEL', 'INFO'),
        "private_key_secret": account.private_key_password,
        "bootstrap": bootstrap,
        "root_directory": root_directory,
        "services": services
    }
    return data
