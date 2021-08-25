'''
/data API

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''


import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, Request

# from byoda.datatypes import IdType

from byoda.models import DataRequest, DataResponseModel

from ..dependencies.podrequest_auth import PodRequestAuth

_LOGGER = logging.getLogger(__name__)

router = APIRouter(
    prefix='/api/v1/member',
    dependencies=[]
)


@router.get('/data', response_model=DataResponseModel)
def get_data(request: Request, data_request: DataRequest,
             auth: PodRequestAuth = Depends(PodRequestAuth)):
    '''
    Get data of the member of a service.
    The data request is evaluated against the schema of the service
    using the identify specified in the client cert.
    '''

    response = DataResponseModel(
        member_id=uuid4(),
        service_id=1,
        data={},
        stats={}
    )
    return response
