'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import Optional

from fastapi import Header, HTTPException, Request

from byoda import config

from byoda.requestauth.requestauth import RequestAuth
from byoda.requestauth.requestauth import TlsStatus

from byoda.datatypes import IdType

from byoda.exceptions import MissingAuthInfo

_LOGGER = logging.getLogger(__name__)


class AccountRequestAuthFast(RequestAuth):
    def __init__(self,
                 request: Request,
                 x_client_ssl_verify: Optional[TlsStatus] = Header(None),
                 x_client_ssl_subject: Optional[str] = Header(None),
                 x_client_ssl_issuing_ca: Optional[str] = Header(None)):
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
        server = config.server

        try:
            super().__init__(
                x_client_ssl_verify or TlsStatus.NONE, x_client_ssl_subject,
                x_client_ssl_issuing_ca, None, request.client.host
            )
        except MissingAuthInfo:
            raise HTTPException(
                status_code=401,
                detail=(
                    'This API requires a TLS client cert or JWT for '
                    'authentication'
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
                 x_client_ssl_verify: Optional[TlsStatus] = Header(None),
                 x_client_ssl_subject: Optional[str] = Header(None),
                 x_client_ssl_issuing_ca: Optional[str] = Header(None)):
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
        server = config.server

        try:
            super().__init__(
                x_client_ssl_verify or TlsStatus.NONE, x_client_ssl_subject,
                x_client_ssl_issuing_ca, None, request.client.host
            )
        except MissingAuthInfo:
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
