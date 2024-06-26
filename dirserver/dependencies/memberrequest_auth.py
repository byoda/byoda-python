'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from logging import getLogger
from byoda.util.logger import Logger

from typing import Annotated

from fastapi import Request
from fastapi import HTTPException
from fastapi import Header
from fastapi import Depends

from byoda.datatypes import IdType

from byoda.servers.server import Server

from byoda.requestauth.requestauth import RequestAuth, TlsStatus

from byoda.exceptions import ByodaMissingAuthInfo

from byoda import config

_LOGGER: Logger = getLogger(__name__)


class MemberRequestAuthOptionalFast(RequestAuth):
    def __init__(self, request: Request,
                 x_client_ssl_verify: TlsStatus | None = Header(None),
                 x_client_ssl_subject: str | None = Header(None),
                 x_client_ssl_issuing_ca: str | None = Header(None),
                 x_client_ssl_cert: str | None = Header(None)):
        '''
        Get the optional authentication info for the client that made the API
        call.

        The reverse proxy has already validated that the client calling
        the API is the owner of the private key for the certificate it
        presented so we trust the HTTP headers set by the reverse proxy

        :raises: HTTPException
        '''

        _LOGGER.debug('verifying authentication with a member cert')

        super().__init__(request.client.host, request.method)

        self.x_client_ssl_verify: TlsStatus = x_client_ssl_verify
        self.x_client_ssl_subject: str = x_client_ssl_subject
        self.x_client_ssl_issuing_ca: str = x_client_ssl_issuing_ca
        self.x_client_ssl_cert: str | None = x_client_ssl_cert
        self.authorization: str = None

    async def authenticate(self):
        server: Server = config.server
        try:
            await super().authenticate(
                self.x_client_ssl_verify or TlsStatus.NONE,
                self.x_client_ssl_subject,
                self.x_client_ssl_issuing_ca,
                self.x_client_ssl_cert,
                self.authorization
            )
        except ByodaMissingAuthInfo:
            return

        if self.id_type != IdType.MEMBER:
            _LOGGER.debug(
                f'Authentication with {self.id_type} cert instead of '
                f'member cert'
            )
            raise HTTPException(status_code=403)

        try:
            _LOGGER.debug('Checking the member cert')
            self.check_member_cert(self.service_id, server.network)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=exc.message)
        except PermissionError:
            _LOGGER.debug('Invalid cert')
            raise HTTPException(status_code=403, detail='Permission denied')

        self.is_authenticated = True


class MemberRequestAuthFast(RequestAuth):
    def __init__(self, request: Request,
                 x_client_ssl_verify: TlsStatus | None = Header(None),
                 x_client_ssl_subject: str | None = Header(None),
                 x_client_ssl_issuing_ca: str | None = Header(None),
                 x_client_ssl_cert: str | None = Header(None)):
        '''
        Get the optional authentication info for the client that made the API
        call.

        The reverse proxy has already validated that the client calling
        the API is the owner of the private key for the certificate it
        presented so we trust the HTTP headers set by the reverse proxy

        :raises: HTTPException
        '''

        _LOGGER.debug('verifying authentication with a member cert')
        server: Server = config.server

        super().__init__(request.client.host, request.method)

        self.x_client_ssl_verify: TlsStatus | None = x_client_ssl_verify
        self.x_client_ssl_subject: str | None = x_client_ssl_subject
        self.x_client_ssl_issuing_ca: str | None = x_client_ssl_issuing_ca
        self.x_client_ssl_cert: str | None = x_client_ssl_cert

        if server.service:
            self.service_id = server.service.service_id
        else:
            self.service_id = None

        self.authorization: str = None

    async def authenticate(self):
        server: Server = config.server
        try:
            await super().authenticate(
                self.x_client_ssl_verify or TlsStatus.NONE,
                self.x_client_ssl_subject,
                self.x_client_ssl_issuing_ca,
                self.x_client_ssl_cert,
                self.authorization
            )
        except ByodaMissingAuthInfo:
            _LOGGER.debug('No authentication provided')
            raise HTTPException(
                status_code=403, detail='Authentication failed'
            )

        if self.id_type != IdType.MEMBER:
            _LOGGER.debug(
                f'Authentication with {self.id_type} cert instead of '
                f'member cert'
            )
            raise HTTPException(status_code=403)

        try:
            _LOGGER.debug('Checking the member cert')
            self.check_member_cert(self.service_id, server.network)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=exc.message)
        except PermissionError:
            _LOGGER.debug('Invalid member cert')
            raise HTTPException(status_code=403, detail='Permission denied')

        self.is_authenticated = True


AuthDep = Annotated[MemberRequestAuthFast, Depends(MemberRequestAuthFast)]
AuthOptionalDep = Annotated[
    MemberRequestAuthOptionalFast, Depends(MemberRequestAuthOptionalFast)
]
