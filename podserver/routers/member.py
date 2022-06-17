'''
/data API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''


import logging
import orjson

from fastapi import APIRouter
from fastapi import UploadFile
from fastapi import Depends
from fastapi import Request
from fastapi import HTTPException

from byoda.datamodel.service import Service
from byoda.datamodel.account import Account
from byoda.datamodel.network import Network
from byoda.datamodel.member import Member

from byoda.datatypes import VisibilityType
from byoda.datatypes import StorageType

from byoda.models import MemberResponseModel
from byoda.models import UploadResponseModel

from byoda import config

from byoda.servers.pod_server import PodServer

from ..dependencies.pod_api_request_auth import PodApiRequestAuth

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/pod', dependencies=[])


@router.get(
    '/member/service_id/{service_id}',
    response_model=MemberResponseModel
)
async def get_member(request: Request, service_id: int,
                     auth: PodApiRequestAuth = Depends(PodApiRequestAuth)):
    '''
    Get metadata for the membership of a service.

    :param service_id: service_id of the service
    :raises: HTTPException 404
    '''

    _LOGGER.debug(f'GET Member API called from {request.client.host}')
    await auth.authenticate()

    account: Account = config.server.account

    # Authorization: handled by PodApiRequestsAuth, which checks the
    # cert / JWT was for an account and its account ID matches that
    # of the pod

    # Make sure we have the latest updates of memberships
    await account.load_memberships()
    member: Member = account.memberships.get(service_id)

    if not member:
        raise HTTPException(
            status_code=404,
            detail=f'Not a member of service with ID {service_id}'
        )

    return member.as_dict()


@router.post('/member/service_id/{service_id}/version/{version}',
             response_model=MemberResponseModel)
async def post_member(request: Request, service_id: int, version: int,
                      auth: PodApiRequestAuth = Depends(PodApiRequestAuth)):
    '''
    Become a member of a service.
    :param service_id: service_id of the service
    :param version: version of the service schema
    :raises: HTTPException 409
    '''

    _LOGGER.debug(f'Post Member API called from {request.client.host}')
    await auth.authenticate()

    account: Account = config.server.account

    # Authorization: handled by PodApiRequestsAuth, which checks the
    # cert / JWT was for an account and its account ID matches that
    # of the pod

    # Make sure we have the latest updates of memberships
    await account.load_memberships()
    member: Member = account.memberships.get(service_id)

    if member:
        raise HTTPException(
            status_code=409,
            detail=(
                f'Already member of service {member.schema.name}({service_id})'
            )
        )

    _LOGGER.debug(f'Joining service {service_id}')
    # BUG: any additional workers also need to join the service
    member = await account.join(service_id, version)

    _LOGGER.debug(f'Returning info about joined service {service_id}')
    return member.as_dict()


@router.put('/member/service_id/{service_id}/version/{version}',
            response_model=MemberResponseModel)
async def put_member(request: Request, service_id: int, version: int,
                     auth: PodApiRequestAuth = Depends(PodApiRequestAuth)):
    '''
    Update the membership of the service to the specified version.
    :param service_id: service_id of the service
    :param version: version of the service schema
    :raises: HTTPException 409
    '''

    _LOGGER.debug(f'Put Member API called from {request.client.host}')
    await auth.authenticate()

    server: PodServer = config.server
    account: Account = server.account

    # Authorization: handled by PodApiRequestsAuth, which checks the
    # cert / JWT was for an account and its account ID matches that
    # of the pod

    await account.load_memberships()
    member: Member = account.memberships.get(service_id)

    if not member:
        raise HTTPException(
            status_code=404,
            detail=f'Not a member of service with ID {service_id}'
        )

    current_version = member.schema.version
    if current_version == version:
        raise HTTPException(
            status_code=409,
            detail=(
                f'Already a member of service {service_id} with version '
                f'{version}'
            )
        )

    if current_version > version:
        raise HTTPException(
            status_code=409, detail=(
                'Can not downgrade membership from version '
                f'{current_version} to {version}'
            )
        )

    # Get the latest list of services from the directory server
    await server.get_registered_services()
    network: Network = account.network
    service_summary = network.service_summaries.get(service_id)
    if not service_summary:
        raise HTTPException(
            status_code=404,
            detail=(
                f'Service {service_id} not available in network '
                f'{network.network}'
            )
        )

    if service_summary['version'] != version:
        raise HTTPException(
            status_code=404,
            detail=(
                f'Version {version} for service {service_id} not known in '
                'the network'
            )
        )

    service: Service = network.services.get(service_id)
    if not service:
        raise ValueError(f'Service {service_id} not found in the membership')

    if not service.schema:
        raise ValueError(f'Schema for service {service_id} not loaded')

    if service.schema.version != version:
        text = service.dowload_schema(save=False)
        contract_data = orjson.loads(text)
        contract_version = contract_data['version']
        if contract_data['version'] != version:
            raise HTTPException(
                status_code=404,
                detail=(
                    f'Service {service_id} only has version {contract_version}'
                    ' available'
                )
            )

        service.save_schema(contract_data)

        # Load the newly downloaded and saved schema.
        member.load_schema()

        # We create a new instance of the Service as to make sure
        # we fully initialize all the applicable data structures
        new_service = Service.get_service(network)
        network.services[service_id] = new_service

        # BUG: any additional workers also need to join the service
        member.upgrade()


@router.post('/member/upload/service_id/{service_id}/visibility/{visibility}/filename/{filename}',
             response_model=UploadResponseModel)
async def post_member_upload(request: Request, file: UploadFile,
                             service_id: int, visibility: VisibilityType,
                             filename: str = None,
                             auth: PodApiRequestAuth =
                             Depends(PodApiRequestAuth)):
    '''
    Become a member of a service.
    :param service_id: service_id of the service
    :param version: version of the service schema
    :raises: HTTPException 409
    '''

    _LOGGER.debug(f'Post Member Upload API called from {request.client.host}')

    await auth.authenticate(service_id=service_id)

    account: Account = config.server.account
    await account.load_memberships()
    member: Member = account.memberships.get(service_id)

    if not member:
        raise HTTPException(status_code=401, detail='Authentication failure')

    # Authorization: handled by PodApiRequestsAuth, which checks the
    # cert / JWT was for an account and its member_id ID matches that
    # of the pod
    if auth.member_id != member.member_id:
        _LOGGER.warning(
            f'Member REST API called by a member {auth.member_id}'
            f'that is not us ({member.member_id})'
        )
        raise HTTPException(
            status_code=401, detail='Authentication failure'
        )

    # Make sure we have the latest updates of memberships
    storage_driver = config.server.storage_driver

    _LOGGER.debug(
        f'Uploading file {file.filename} for service {service_id} with '
        f'visibility {visibility}'
    )

    storage_type = StorageType.PRIVATE
    if visibility in (VisibilityType.KNOWN, VisibilityType.PUBLIC):
        storage_type = StorageType.PUBLIC

    if not filename:
        filename = file.file

    await storage_driver.write(
        filename, data=None,
        file_descriptor=file.file,
        storage_type=storage_type
    )

    location = storage_driver.get_url(
        filepath=filename, storage_type=storage_type
    )

    _LOGGER.debug(f'Returning info about file uploaded to {location}')
    return {
        'service_id': service_id,
        'location': location,
    }
