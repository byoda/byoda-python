'''
API for submitting App certificates for signature by the service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''


from logging import Logger, getLogger


from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi import HTTPException

from cryptography import x509

from byoda.datatypes import IdType
from byoda.datatypes import AuthSource

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service

from byoda.secrets.secret import Secret
from byoda.secrets.appsca_secret import AppsCaSecret

from byoda.storage.filestorage import FileStorage
from byoda.models import CertSigningRequestModel

from byoda.util.paths import Paths

from byoda.servers.service_server import ServiceServer

from byoda import config

from ..dependencies.apprequest_auth import AppRequestAuthOptionalFast

_LOGGER: Logger = getLogger(__name__)

MAX_CSR_LENGTH: int = 16384

router: APIRouter = APIRouter(
    prefix='/api/v1/service',
    dependencies=[]
)


@router.post('/app', status_code=201)
async def post_app(request: Request, csr: CertSigningRequestModel,
                   auth: AppRequestAuthOptionalFast =
                   Depends(AppRequestAuthOptionalFast)) -> None:
    '''
    Submit a Certificate Signing Request for the Member certificate
    and get the cert signed by the Service Members CA
    This API is called by pods
    This API does not require authentication, it needs to be rate
    limited by the reverse proxy (TODO: security)
    '''

    _LOGGER.debug(f'POST App API called from {request.client.host}')

    await auth.authenticate()

    server: ServiceServer = config.server
    service: Service = server.service
    network: Network = server.network
    paths: Paths = service.paths
    storage_driver: FileStorage = server.storage_driver

    if len(csr.csr) > MAX_CSR_LENGTH:
        raise HTTPException(
            status_code=401, detail='CSR too long'
        )

    # Authorization
    csr_x509: x509 = Secret.csr_from_string(csr.csr)
    common_name = Secret.extract_commonname(csr_x509)

    try:
        csr_entity_id = AppsCaSecret.review_commonname_by_parameters(
            common_name, network.name, service.service_id
        )
    except PermissionError:
        raise HTTPException(
            status_code=401, detail=f'Invalid common name {common_name} in CSR'
        )
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=400, detail=(
                f'error when reviewing the common name {common_name} in your '
                'CSR'
            )
        )

    if csr_entity_id.id_type == IdType.APP:
        csr_filepath: str = paths.get(
            Paths.APP_CSR_FILE, app_id=csr_entity_id.id
        )
        cert_filepath: str = paths.get(
            Paths.APP_CERT_FILE, app_id=csr_entity_id.id
        )
    elif csr_entity_id.id_type == IdType.APP_DATA:
        csr_filepath: str = paths.get(
            Paths.APP_DATA_CSR_FILE, app_id=csr_entity_id.id
        )
        cert_filepath: str = paths.get(
            Paths.APP_DATA_CERT_FILE, app_id=csr_entity_id.id
        )
    else:
        raise HTTPException(
            status_code=403,
            detail='This API only signs APP and APP_DATA CSRs'
        )

    if auth.is_authenticated:
        if auth.auth_source != AuthSource.CERT:
            raise HTTPException(
                status_code=401,
                detail=(
                    'When used with credentials, this API requires '
                    'authentication with a TLS client cert'
                )
            )

        if csr_entity_id.id_type != IdType.APP:
            raise HTTPException(
                status_code=403,
                detail='A TLS cert of an app must be used with this API'
            )

        if csr_entity_id.id != auth.app_id:
            raise HTTPException(
                status_code=403,
                detail=(
                    'The app_id in the CSR does not match the app_id in the '
                    'TLS client cert'
                )
            )
        _LOGGER.debug(f'CSR for existing app {csr_entity_id.id}')
    else:
        if (await storage_driver.exists(csr_filepath)
                or await storage_driver.exists(cert_filepath)):
            raise HTTPException(
                status_code=403,
                detail=(
                    'Requests for renewal of an app data cert must use '
                    'authentication'
                )
            )

        _LOGGER.debug(f'Csr for new app {csr_entity_id.id}')
    # End of Authorization

    if csr_entity_id.service_id is None:
        raise ValueError(
            f'No service id found in common name {common_name}'
        )

    if csr_entity_id.service_id != service.service_id:
        raise HTTPException(
            404, f'Incorrect service_id in common name {common_name}'
        )

    # We do not sign the CSR here, as this is an off-line process
    await storage_driver.write(csr_filepath, csr.csr)
    _LOGGER.info(f'Saved CSR with commonname {common_name} to {csr_filepath}')
