'''
request_auth for authentication with an account cert

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from typing import Annotated
from logging import getLogger
from byoda.util.logger import Logger

from fastapi import Request
from fastapi import HTTPException
from fastapi import Header
from fastapi import Depends

from byoda.requestauth.requestauth import RequestAuth
from byoda.requestauth.requestauth import TlsStatus

from byoda.datatypes import IdType

from byoda.servers.app_server import AppServer
from byoda.exceptions import ByodaMissingAuthInfo

from byoda import config

_LOGGER: Logger = getLogger(__name__)


class AccountRequestAuthFast(RequestAuth):
    def __init__(self,
                 request: Request,
                 x_client_ssl_verify: TlsStatus | None = Header(None),
                 x_client_ssl_subject: str | None = Header(None),
                 x_client_ssl_issuing_ca: str | None = Header(None),
                 x_client_ssl_cert: str | None = Header(None)) -> None:
        '''
        Get the authentication info for the client that made the API call.
        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

        :param request: Starlette request instance
        :returns: (n/a)
        :raises: HTTPException
        '''

        _LOGGER.debug('Verifying authentication with an account cert')

        super().__init__(request.client.host, request.method)

        self.x_client_ssl_verify: TlsStatus | None = x_client_ssl_verify
        self.x_client_ssl_subject: str | None = x_client_ssl_subject
        self.x_client_ssl_issuing_ca: str | None = x_client_ssl_issuing_ca
        self.x_client_ssl_cert: str | None = x_client_ssl_cert
        self.authorization: str | None = None

    async def authenticate(self) -> None:
        server: AppServer = config.server

        try:
            await super().authenticate(
                self.x_client_ssl_verify, self.x_client_ssl_subject,
                self.x_client_ssl_issuing_ca, self.x_client_ssl_cert, None
            )
        except ByodaMissingAuthInfo:
            raise HTTPException(
                status_code=401,
                detail=(
                    'This API requires a TLS client cert for authentication'
                )
            )

        if self.id_type != IdType.ACCOUNT:
            raise HTTPException(
                status_code=403,
                detail='Must authenticate with a credential for an account'
            )

        try:
            _LOGGER.debug('Checking the account cert')
            self.check_account_cert(server.network)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=exc.message)
        except PermissionError:
            raise HTTPException(status_code=403, detail='Permission denied')

        self.is_authenticated = True


AuthDep = Annotated[AccountRequestAuthFast, Depends(AccountRequestAuthFast)]