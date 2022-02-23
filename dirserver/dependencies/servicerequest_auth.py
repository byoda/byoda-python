'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import Optional

from byoda import config

from fastapi import Header, HTTPException, Request

from byoda.datatypes import IdType

from byoda.requestauth.requestauth import RequestAuth, TlsStatus
from byoda.exceptions import MissingAuthInfo

_LOGGER = logging.getLogger(__name__)


class ServiceRequestAuthFast(RequestAuth):
    def __init__(self,
                 request: Request,
                 x_client_ssl_verify: Optional[TlsStatus] = Header(None),
                 x_client_ssl_subject: Optional[str] = Header(None),
                 x_client_ssl_issuing_ca: Optional[str] = Header(None)):
        '''
        Get the authentication info for the client that made the API call.

        Authentication to the directory server must use the TLS certificate,
        authentication based on JWT is not permitted.

        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

        :param request: Starlette request instance
        :param service_id: the service identifier for the service
        :returns: (n/a)
        :raises: HTTPException
        '''

        _LOGGER.debug('verifying authentication with a service cert')
        try:
            super().__init__(
                x_client_ssl_verify or TlsStatus.NONE, x_client_ssl_subject,
                x_client_ssl_issuing_ca, None, request.client.host
            )
        except MissingAuthInfo:
            raise HTTPException(
                status_code=401, detail='Authentication failed'
            )

        if self.id_type != IdType.SERVICE:
            raise HTTPException(
                status_code=403,
                detail='Must authenticate with a credential for a service'
            )

        # We verify the cert chain by creating dummy secrets for each
        # applicable CA and then review if that CA would have signed
        # the commonname found in the certchain presented by the
        # client.
        try:
            _LOGGER.debug('Checking service cert')
            self.check_service_cert(config.server.network)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=exc.message)
        except PermissionError:
            raise HTTPException(status_code=403, detail='Permission denied')

        self.is_authenticated = True


class ServiceRequestOptionalAuthFast(RequestAuth):
    def __init__(self,
                 request: Request,
                 x_client_ssl_verify: Optional[TlsStatus] = Header(None),
                 x_client_ssl_subject: Optional[str] = Header(None),
                 x_client_ssl_issuing_ca: Optional[str] = Header(None)):
        '''
        Get the authentication info for the client that made the API call.
        With this class, authentication is optional. If no authentication
        information is provided, the property 'is_authenticated' will have
        a value of False. If authentication is provided but it is invalid,
        a HTTP 401 will be returned. If authentication is provided, is valid
        but is not authorized to call the API then a HTTP 403 will be returned

        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

        :param request: Starlette request instance
        :param service_id: the service identifier for the service
        :raises: HTTPException
        '''

        _LOGGER.debug('verifying authentication with a service cert')
        try:
            super().__init__(
                x_client_ssl_verify or TlsStatus.NONE, x_client_ssl_subject,
                x_client_ssl_issuing_ca, None, request.client.host
            )
        except MissingAuthInfo:
            return

        if self.id_type != IdType.SERVICE:
            raise HTTPException(
                status_code=403,
                detail='Must authenticate with a credential for a service'
            )

        # We verify the cert chain by creating dummy secrets for each
        # applicable CA and then review if that CA would have signed
        # the commonname found in the certchain presented by the
        # client.
        try:
            _LOGGER.debug('Checking service cert')
            self.check_service_cert(config.server.network)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=exc.message)
        except PermissionError:
            raise HTTPException(status_code=403, detail='Permission denied')

        self.is_authenticated = True
