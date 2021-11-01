'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from typing import Optional

from byoda import config

from fastapi import Header, HTTPException, Request

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
        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

        :param request: Starlette request instance
        :param service_id: the service identifier for the service
        :returns: (n/a)
        :raises: HTTPException
        '''

        try:
            super().__init__(
                x_client_ssl_verify or TlsStatus.NONE, x_client_ssl_subject,
                x_client_ssl_issuing_ca, request.client.host
            )
        except MissingAuthInfo:
            raise HTTPException(
                status_code=401, detail='Authentication failed'
            )

        if self.client_cn is None and self.issuing_ca_cn is None:
            raise HTTPException(
                status_code=401, detail='Authentication failed'
            )

        # We verify the cert chain by creating dummy secrets for each
        # applicable CA and then review if that CA would have signed
        # the commonname found in the certchain presented by the
        # client.
        self.check_service_cert(config.server.network)

        self.is_authenticated = True
