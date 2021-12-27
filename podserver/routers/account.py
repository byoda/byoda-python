'''
/pod/account API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''


import os
import logging

from fastapi import APIRouter, Depends, Request

from byoda.datatypes import StorageType

from byoda.models import AccountResponseModel

from byoda import config

from ..dependencies.podrequest_auth import PodRequestAuth

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/pod', dependencies=[])


@router.get('/account', response_model=AccountResponseModel)
def get_account(request: Request,
                auth: PodRequestAuth = Depends(PodRequestAuth)):
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

    services = []
    for service in network.services:
        service_id = service.service_id
        if service_id in account.memberships:
            member = account.memberships[service_id]
            joined = True
            join_version = member.schema.version
        else:
            joined = False
            join_version = None

        services.append(
            {
                'service_id': service.service_id,
                'name': service.name,
                'latest_contract_version': service.version,
                'member': joined,
                'accepted_contract_version': join_version
            }
        )

    response = AccountResponseModel(
        account_id=server.account.account_id,
        network=server.network.network,
        started=str(server.started),
        cloud=doc_store.backend.cloud_type,
        private_bucket=doc_store.backend.buckets[StorageType.PRIVATE.value],
        public_bucket=doc_store.backend.buckets[StorageType.PUBLIC.value],
        loglevel=os.environ.get('LOGLEVEL', 'INFO'),
        private_key_secret=account.private_key_password,
        bootstrap=os.environ.get('BOOTSTRAP', 'False'),
        services=services
    )

    data = {
        "account_id": server.account.account_id,
        "network": server.network.network,
        "started": str(server.started),
        "cloud": doc_store.backend.cloud_type,
        "private_bucket": doc_store.backend.buckets[StorageType.PRIVATE.value],
        "public_bucket": doc_store.backend.buckets[StorageType.PUBLIC.value],
        "loglevel": os.environ.get('LOGLEVEL', 'INFO'),
        "private_key_secret": account.private_key_password,
        "bootstrap": os.environ.get('BOOTSTRAP', 'False'),
        "services": services
    }
    return data
