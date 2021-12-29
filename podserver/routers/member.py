'''
/data API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''


import logging
import json

from fastapi import APIRouter, Depends, Request, HTTPException

from byoda.datamodel import Service

from byoda.models import MemberResponseModel

from byoda import config

from ..dependencies.podrequest_auth import PodRequestAuth

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/pod', dependencies=[])


@router.get('/member', response_model=MemberResponseModel)
def get_member(request: Request, service_id: int,
               auth: PodRequestAuth = Depends(PodRequestAuth)):
    '''
    Get metadata for the membership of a service.

    :param service_id: service_id of the service
    :raises: HTTPException 404
    '''

    account = config.server.account

    member = account.memberships.get(service_id)
    if not member:
        raise HTTPException(
            status_code=404,
            detail='Not a member of service with ID {service_id}'
        )

    return member.as_dict()


@router.post('/member', response_model=MemberResponseModel)
def post_member(request: Request, service_id: int, version: int,
                auth: PodRequestAuth = Depends(PodRequestAuth)):
    '''
    Become a member of a service.
    :param service_id: service_id of the service
    :param version: version of the service schema
    :raises: HTTPException 409
    '''

    account = config.server.account

    member = account.memberships.get(service_id)
    if member:
        raise HTTPException(
            status_code=409,
            detail=(
                f'Already member of service {member.schema.name}({service_id})'
            )
        )

    member = account.join(service_id, version)

    return member.as_dict()


@router.patch('/member', response_model=MemberResponseModel)
def patch_member(request: Request, service_id: int, version: int,
                 auth: PodRequestAuth = Depends(PodRequestAuth)):
    '''
    Update the membership of the service to the specified version.
    :param service_id: service_id of the service
    :param version: version of the service schema
    :raises: HTTPException 409
    '''

    server = config.server
    account = server.account

    member = account.memberships.get(service_id)
    if not member:
        raise HTTPException(
            status_code=404,
            detail='Not a member of service with ID {service_id}'
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
    server.get_registered_services()
    network = account.network
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

    service = network.services.get(service_id)
    if not service:
        raise ValueError(f'Service {service_id} not found in the membership')

    if not service.schema:
        raise ValueError(f'Schema for service {service_id} not loaded')

    if service.schema.version != version:
        text = service.dowload_schema(save=False)
        contract_data = json.loads(text)
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

        member.upgrade()
