'''
memberdata API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''


from logging import getLogger
from byoda.util.logger import Logger

from fastapi import APIRouter
from fastapi import Request
from fastapi import HTTPException

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.models import AccountDataDownloadResponseModel

from byoda.datatypes import IdType

from byoda.servers.pod_server import PodServer

from byoda import config

from ..dependencies.pod_api_request_auth import AuthDep

_LOGGER: Logger = getLogger(__name__)

router: APIRouter = APIRouter(prefix='/api/v1/pod', dependencies=[])


@router.get(
    '/account/data/service_id/{service_id}',
    response_model=AccountDataDownloadResponseModel
)
async def get_accountdata(request: Request, service_id: int, auth: AuthDep):
    '''
    Get metadata for the membership of a service.

    :param service_id: service_id of the service
    :raises: HTTPException 404
    '''

    server: PodServer = config.server
    account: Account = server.account

    _LOGGER.debug(
        f'GET Account Data API called for service {service_id} '
        f'from {request.client.host}'
    )

    await auth.authenticate(account)

    member: Member = await account.get_membership[service_id]

    if not member:
        raise HTTPException(
            status_code=404,
            detail=f'Not a member of service with ID {service_id}'
        )

    # Data import/export apis can
    if auth.id_type != IdType.ACCOUNT or auth.account_id != account.account_id:
        raise HTTPException(
            status_code=401, detail='Not authorized to access this service'
        )

    #
    # End of authorization
    #

    # TODO: refactor account data export now that we've migrated from
    # object storage to SQL storage

    # await member.load_data()

    # return {'data': member.data}
    return {'data': {}}
