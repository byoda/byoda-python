'''
/network/service API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3

The registration of a service in the network takes four steps:
1: Create a Service CA key/cert and request signature by the Network Services
   CA via a POST /api/v1/network/service request.
2: Register the service and its data cert using a
   PUT /api/v1/network/service/{service_id} request.
3: Submit the service-signed schema for the service and get it signed by
   the network using the PATCH /api/v1/network/service request.
4: Download the fully signed schema and publish it on the web site for the
   service using the GET /api/v1/network/service request.
'''


from logging import getLogger
from byoda.util.logger import Logger

from fastapi import APIRouter, Request
from fastapi import HTTPException

from byoda.models import SchemaModel

from byoda import config

_LOGGER: Logger = getLogger(__name__)

router: APIRouter = APIRouter(
    prefix='/api/v1/service',
    dependencies=[]
)


@router.get('/service/{service_id}', response_model=SchemaModel)
def get_service(request: Request, service_id: int):
    '''
    Get either the data contract of the specified service or a list of
    summaries of the available services. This API is called by pods
    This API does not require authentication as service schemas are
    public information
    '''

    _LOGGER.debug(
        f'GET Service API for service_id {service_id} '
        f'called from {request.client.host}'
    )

    # Authorization: not required, public API
    if service_id != config.server.service.service_id:
        _LOGGER.info(
            f'Service schema requested for incorrect service: {service_id}'
        )
        return HTTPException(404)
    # End of authorization

    schema = config.server.service.schema

    if not schema or not schema.json_schema:
        _LOGGER.exception('Schema not defined for the service')
        raise HTTPException(503)

    return schema.json_schema
