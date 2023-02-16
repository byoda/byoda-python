'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from fastapi import Header, HTTPException, Request

from byoda import config

from byoda.requestauth.requestauth import RequestAuth
from byoda.requestauth.requestauth import TlsStatus

from byoda.datatypes import IdType

from byoda.exceptions import ByodaMissingAuthInfo

_LOGGER = logging.getLogger(__name__)


class AccountRequestAuthFast(RequestAuth):
    def __init__(self,
                 request: Request,
                 x_client_ssl_verify: TlsStatus | None = Header(None),
                 x_client_ssl_subject: str | None = Header(None),
                 x_client_ssl_issuing_ca: str | None = Header(None),
                 x_client_ssl_cert: str | None = Header(None)):
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

    async def authenticate(self):
        server = config.server

        try:
            await super().authenticate(
                self.x_client_ssl_verify, self.x_client_ssl_subject,
                self.x_client_ssl_issuing_ca, self.x_client_ssl_cert, None
            )
        except ByodaMissingAuthInfo:
            raise HTTPException(
                status_code=401,
                detail=(
                    'This API requires a TLS client cert for authen tication'
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


class AccountRequestOptionalAuthFast(RequestAuth):
    def __init__(self,
                 request: Request,
                 x_client_ssl_verify: TlsStatus | None = Header(None),
                 x_client_ssl_subject: str | None = Header(None),
                 x_client_ssl_issuing_ca: str | None = Header(None),
                 x_client_ssl_cert: str | None = Header(None)):
        '''
        Get the authentication info for the client that made the API call.
        In this class, authentication is optional, so if no TLS client cert
        is used then authentication will pass but the 'is_authenticated'
        property will have value False

        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

        :param request: Starlette request instance
        :returns: (n/a)
        :raises: HTTPException
        '''

        _LOGGER.debug('verifying authentication with an account cert')

        super().__init__(request.client.host, request.method)

        self.x_client_ssl_verify: TlsStatus | None = x_client_ssl_verify
        self.x_client_ssl_subject: str | None = x_client_ssl_subject
        self.x_client_ssl_issuing_ca: str | None = x_client_ssl_issuing_ca
        self.x_client_ssl_cert: str | None = x_client_ssl_cert
        self.authorization = None

    async def authenticate(self):
        server = config.server

        try:
            await super().authenticate(
                self.x_client_ssl_verify, self.x_client_ssl_subject,
                self.x_client_ssl_issuing_ca, self.x_client_ssl_cert, None
            )
        except ByodaMissingAuthInfo:
            # This class does not require authentication so we just return
            return

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
