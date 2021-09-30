'''
/network/service API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''


import logging

from fastapi import APIRouter, Depends, Request

from byoda.datatypes import IdType

from byoda.models import ServiceSummariesResponseModel

# from byoda.models import LetsEncryptSecretModel

from byoda import config

from ..dependencies.accountrequest_auth import AccountRequestAuthFast

_LOGGER = logging.getLogger(__name__)

router = APIRouter(
    prefix='/api/v1/network',
    dependencies=[]
)


@router.get('/service', response_model=ServiceSummariesResponseModel)
def get_service(request: Request, skip: int = 0, count: int = 0):
    '''
    Get a list of summaries of available services
    '''

    _LOGGER.debug(f'GET Service API called from {request.client.host}')

    network = config.server.network

    services = list(network.services.values())

    if count == 0:
        count = len(services)

    result = {
        'service_summaries': [
            {
                'service_id': service.service_id,
                'version': service.schema.json_schema['version'],
                'name': service.schema.json_schema['name'],
                'title': service.schema.json_schema.get('title'),
                'description': service.schema.json_schema.get('description'),
                'supportemail': service.schema.json_schema.get('supportemail'),
            } for service in services[skip: count]
        ]
    }
    return result
