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

from byoda.requestauth.requestauth import RequestAuth, TlsStatus
from byoda.exceptions import MissingAuthInfo

_LOGGER = logging.getLogger(__name__)


class MemberRequestAuthFast(RequestAuth):
    def __init__(self, request: Request,
                 x_client_ssl_verify: Optional[TlsStatus] = Header(None),
                 x_client_ssl_subject: Optional[str] = Header(None),
                 x_client_ssl_issuing_ca: Optional[str] = Header(None)):
        '''
        Get the authentication info for the client that made the API call.
        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

        :param service_id: the service identifier for the service
        :returns: (n/a)
        :raises: HTTPException
        '''

        _LOGGER.debug('verifying authentication with a member cert')
        server = config.server

        try:
            super().__init__(
                x_client_ssl_verify or TlsStatus.NONE, x_client_ssl_subject,
                x_client_ssl_issuing_ca, None, request.client.host
            )
        except MissingAuthInfo:
            raise HTTPException(
                status_code=403, detail='Authentication failed'
            )

        if self.client_cn is None and self.issuing_ca_cn is None:
            raise HTTPException(
                status_code=401, detail='Authentication missing'
            )

        try:
            _LOGGER.debug('Checking the member cert')
            self.check_member_cert(self.service_id, server.network)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=exc.message)
        except PermissionError:
            raise HTTPException(status_code=403, detail='Permission denied')

        self.is_authenticated = True
