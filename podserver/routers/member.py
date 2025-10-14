'''
/data API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from uuid import UUID
from logging import Logger
from logging import getLogger

import orjson


from fastapi import APIRouter
from fastapi import UploadFile
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

from byoda.storage.filestorage import FileStorage

from byoda import config

from byoda.servers.pod_server import PodServer
from byoda.util.paths import Paths

from ..dependencies.pod_api_request_auth import AuthDep

_LOGGER: Logger = getLogger(__name__)

router = APIRouter(prefix='/api/v1/pod', dependencies=[])


@router.get(
    '/member/service_id/{service_id}',
    response_model=MemberResponseModel
)
async def get_member(request: Request, service_id: int, auth: AuthDep):
    '''
    Get metadata for the membership of a service.

    :param service_id: service_id of the service
    :raises: HTTPException 404
    '''

    server: PodServer = config.server
    account: Account = server.account

    log_data: dict[str, any] = {
        'remote_addr': request.client.host,
        'service_id': service_id,
    }
    _LOGGER.debug('GET Member API called', extra=log_data)
    await auth.authenticate(account)

    # Authorization: handled by PodApiRequestsAuth, which checks the
    # cert / JWT was for an account and its account ID matches that
    # of the pod

    # Make sure we have the latest updates of memberships
    member: Member = await account.get_membership(service_id)

    if not member:
        _LOGGER.debug('Not a member of service', extra=log_data)
        raise HTTPException(
            status_code=404,
            detail=f'Not a member of service with ID {service_id}'
        )

    return member.as_dict()


@router.post('/member/service_id/{service_id}/version/{version}',
             response_model=MemberResponseModel)
async def post_member(request: Request, service_id: int, version: int,
                      auth: AuthDep):
    '''
    Become a member of a service.

    :param service_id: service_id of the service
    :param version: version of the service schema
    :raises: HTTPException 409
    '''

    server: PodServer = config.server
    account: Account = server.account

    log_data: dict[str, any] = {
        'remote_addr': request.client.host,
        'service_id': service_id,
        'schema_version': version,
    }
    _LOGGER.debug('Post Member API called', extra=log_data)
    await auth.authenticate(account)

    local_storage: FileStorage = server.local_storage

    # Authorization: handled by PodApiRequestsAuth, which checks the
    # cert / JWT was for an account and its account ID matches that
    # of the pod

    # Make sure we have the latest updates of memberships
    member: Member = await account.get_membership(service_id)

    if member:
        _LOGGER.debug('Already a member of the service', extra=log_data)
        raise HTTPException(
            status_code=409,
            detail=(
                f'Already member of service {member.schema.name}({service_id})'
            )
        )

    _LOGGER.debug('Joining service', extra=log_data)
    # TODO: restart the gunicorn webserver when we join a service
    member = await account.join(service_id, version, local_storage)

    _LOGGER.debug('Returning info about joined service', extra=log_data)
    return member.as_dict()


@router.put('/member/service_id/{service_id}/version/{version}',
            response_model=MemberResponseModel)
async def put_member(request: Request, service_id: int, version: int,
                     auth: AuthDep):
    '''
    Update the membership of the service to the specified version.
    :param service_id: service_id of the service
    :param version: version of the service schema
    :raises: HTTPException 409
    '''

    server: PodServer = config.server
    account: Account = server.account

    log_data: dict[str, any] = {
        'remote_addr': request.client.host,
        'service_id': service_id,
        'schema_version': version,
    }

    _LOGGER.debug('Put Member API called', extra=log_data)
    await auth.authenticate(account)

    # Authorization: handled by PodApiRequestsAuth, which checks the
    # cert / JWT was for an account and its account ID matches that
    # of the pod

    member: Member = await account.get_membership(service_id)

    if not member:
        _LOGGER.debug('Not a member of service', extra=log_data)
        raise HTTPException(
            status_code=404,
            detail=f'Not a member of service with ID {service_id}'
        )

    current_version: int = member.schema.version
    log_data['current_schema_version'] = current_version
    if current_version == version:
        if member.tls_secret and member.tls_secret.cert:
            _LOGGER.debug('Updating registraton', extra=log_data)
            await member.update_registration()
            return member.as_dict()
        else:
            _LOGGER.debug(
                'Already a member of service with matching schema version',
                extra=log_data
            )
            raise HTTPException(
                status_code=409,
                detail=(
                    f'Already a member of service {service_id} with version '
                    f'{version}'
                )
            )

    if current_version > version:
        _LOGGER.debug('Can not downgrade membership', extra=log_data)
        raise HTTPException(
            status_code=409, detail=(
                'Can not downgrade membership from version '
                f'{current_version} to {version}'
            )
        )

    # Get the latest list of services from the directory server
    await server.get_registered_services()
    network: Network = account.network
    service_summary: dict[str, any] = network.service_summaries.get(service_id)
    if not service_summary:
        _LOGGER.debug('Service not available in network', extra=log_data)
        raise HTTPException(
            status_code=404,
            detail=(
                f'Service {service_id} not available in network '
                f'{network.network}'
            )
        )

    if service_summary['version'] != version:
        log_data['network_version'] = service_summary['version']
        _LOGGER.debug(
            'Service version not available in network', extra=log_data
        )
        raise HTTPException(
            status_code=404,
            detail=(
                'Version for service not known in the network'
            )
        )

    service: Service = network.services.get(service_id)
    if not service:
        _LOGGER.debug('Service not found in network', extra=log_data)
        raise ValueError(f'Service {service_id} not found in the network')

    if not service.schema:
        _LOGGER.debug('Schema for service not loaded', extra=log_data)
        raise ValueError(f'Schema for service {service_id} not loaded')

    if service.schema.version != version:
        text: str = service.dowload_schema(save=False)
        contract_data: dict[str, any] = orjson.loads(text)
        contract_version = contract_data['version']
        log_data['downloaded_schema_version'] = contract_version
        if contract_data['version'] != version:
            _LOGGER.debug('Service version not available', extra=log_data)
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
        new_service: Service = await Service.get_service(network)
        network.services[service_id] = new_service

        # BUG: any additional workers also need to join the service
        member.upgrade()

    return member.as_dict()


@router.post('/member/upload/service_id/{service_id}/asset_id/{asset_id}/visibility/{visibility}',      # noqa: E501
             response_model=UploadResponseModel)
async def post_member_upload(request: Request, files: list[UploadFile],
                             service_id: int, asset_id: UUID,
                             visibility: VisibilityType, auth: AuthDep):
    '''
    Upload a file so it can be used as media for a post or tweet.

    :param service_id: service_id of the service
    :param version: version of the service schema
    :raises: HTTPException 409
    '''

    server: PodServer = config.server
    account: Account = server.account

    log_data: dict[str, any] = {
        'remote_addr': request.client.host,
        'service_id': service_id,
        'asset_id': asset_id,
        'visibility': visibility,
        'file_count': len(files),
    }
    _LOGGER.debug('Post Member Upload API called', extra=log_data)

    await auth.authenticate(account, service_id=service_id)
    log_data['authenticating_member_id'] = auth.member_id

    member: Member = await account.get_membership(service_id)

    if not member:
        _LOGGER.debug('Not a member of service')
        raise HTTPException(status_code=401, detail='Authentication failure')

    log_data['member_id'] = member.member_id
    # Authorization: handled by PodApiRequestsAuth, which checks the
    # cert / JWT was for an account and its member_id ID matches that
    # of the pod
    if auth.member_id != member.member_id:
        _LOGGER.warning(
            'Member REST API called by a different member', extra=log_data
        )
        raise HTTPException(
            status_code=401, detail='Authentication failure'
        )

    # Make sure we have the latest updates of memberships
    storage_driver: FileStorage = config.server.storage_driver

    _LOGGER.debug('Uploading files', extra=log_data)

    if visibility in (VisibilityType.KNOWN, VisibilityType.PUBLIC):
        storage_type: StorageType = StorageType.PUBLIC
    elif visibility == VisibilityType.RESTRICTED:
        storage_type: StorageType = StorageType.RESTRICTED
    else:
        storage_type: StorageType = StorageType.PRIVATE

    locations: list[str] = []
    cdn_urls: list[str] = []
    for file in files:
        log_data['provided_filename'] = file.filename
        _LOGGER.debug('Uploading file', extra=log_data)
        filepath: str = f'{asset_id}/{file.filename}'
        await storage_driver.write(
            filepath, data=None,
            file_descriptor=file.file, storage_type=storage_type
        )

        location: str = storage_driver.get_url(
            filepath=filepath, storage_type=storage_type
        )
        locations.append(location)

        cdn_url: str | None = None
        if storage_type != StorageType.PRIVATE:
            paths: Paths = member.paths
            cdn_url_template: str = paths.PUBLIC_ASSET_CDN_URL
            if storage_type == StorageType.RESTRICTED:
                cdn_url_template = paths.RESTRICTED_ASSET_CDN_URL

            cdn_url: str = cdn_url_template.format(
                cdn_fqdn=server.cdn_fqdn,
                cdn_origin_site_id=server.cdn_origin_site_id,
                service_id=service_id, member_id=member.member_id,
                asset_id=asset_id, filename=file.filename
            )
            cdn_urls.append(cdn_url)

    _LOGGER.debug('Returning info about uploaded file(s)', extra=log_data)

    return {
        'service_id': service_id,
        'asset_id': asset_id,
        'locations': locations,
        'cdn_urls': cdn_urls
    }
