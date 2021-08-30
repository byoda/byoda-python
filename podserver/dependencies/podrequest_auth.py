'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from typing import Optional

from fastapi import Header, HTTPException, Request

from byoda import config

from byoda.datatypes import IdType

from byoda.requestauth.requestauth import RequestAuth, TlsStatus
from byoda.exceptions import MissingAuthInfo

_LOGGER = logging.getLogger(__name__)


class PodRequestAuth(RequestAuth):
    def __init__(self,
                 request: Request,
                 service_id: Optional[int] = Header(None),
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

        if (x_client_ssl_verify is None or x_client_ssl_subject is None
                or x_client_ssl_issuing_ca is None):
            raise HTTPException(
                status_code=401,
                detail='No MTLS client cert provided'
            )

        try:
            super().__init__(
                x_client_ssl_verify or TlsStatus.NONE, x_client_ssl_subject,
                x_client_ssl_issuing_ca, request.client.host
            )
        except MissingAuthInfo:
            raise HTTPException(
                status_code=400, detail='No authentication provided'
            )

        # This API can be called by ourselves, someone in our network for
        # the service, the services or an approved application of the service
        if self.id_type == IdType.ACCOUNT:
            if service_id:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        'Service ID specified for request authenticated '
                        'with an account secret'
                    )
                )
            self.check_account_cert(config.network)
        elif self.id_type == IdType.MEMBER:
            self.check_member_cert(service_id, config.network)
        elif self.id_type == IdType.SERVICE:
            self.check_service_cert(service_id, config.network)
        else:
            raise HTTPException(
                status_code=400, detail=f'Unknown IdType: {self.id_type}'
            )

        self.is_authenticated = True
