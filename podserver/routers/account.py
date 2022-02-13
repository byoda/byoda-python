'''
/pod/account API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''


import os
import logging

from fastapi import APIRouter, Depends, Request, HTTPException

from byoda.datatypes import StorageType, CloudType

from byoda.models import AccountResponseModel

from byoda import config

from ..dependencies.pod_api_request_auth import PodApiRequestAuth

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/pod', dependencies=[])


@router.get('/account', response_model=AccountResponseModel)
def get_account(request: Request,
                auth: PodApiRequestAuth = Depends(PodApiRequestAuth)):
    '''
    Get data for the pod account.
    The data request is evaluated using the identify specified in the
    client cert.
    '''

    _LOGGER.debug(f'GET Account API called from {request.client.host}')

    server = config.server
    account = server.account
    network = account.network
    doc_store = account.document_store
    if doc_store.backend.cloud_type == CloudType.LOCAL:
        private_bucket = 'LOCAL'
        public_bucket = '/var/www/wwwroot/public'
    else:
        private_bucket = doc_store.backend.buckets[StorageType.PRIVATE.value]
        public_bucket = doc_store.backend.buckets[StorageType.PUBLIC.value]

    bootstrap = os.environ.get('BOOTSTRAP')
    if not bootstrap:
        bootstrap = False
    elif bootstrap.upper() in ('TRUE', 'BOOTSTRAP'):
        bootstrap = True
    else:
        bootstrap = False

    root_directory = account.paths.root_directory

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
        "public_bucket": public_bucket,
        "loglevel": os.environ.get('LOGLEVEL', 'INFO'),
        "private_key_secret": account.private_key_password,
        "bootstrap": bootstrap,
        "root_directory": root_directory,
        "services": services
    }
    return data
