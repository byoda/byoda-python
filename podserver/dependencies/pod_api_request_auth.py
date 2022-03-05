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

from byoda.datamodel.member import GRAPHQL_API_URL_PREFIX
from byoda.datatypes import AuthSource, IdType

from byoda.requestauth.requestauth import RequestAuth, TlsStatus
from byoda.exceptions import MissingAuthInfo

from byoda import config


_LOGGER = logging.getLogger(__name__)


class PodApiRequestAuth(RequestAuth):
    def __init__(self,
                 request: Request,
                 service_id: Optional[int] = Header(None),
                 x_client_ssl_verify: Optional[TlsStatus] = Header(None),
                 x_client_ssl_subject: Optional[str] = Header(None),
                 x_client_ssl_issuing_ca: Optional[str] = Header(None),
                 authorization: Optional[str] = Header(None)):
        '''
        Get the authentication info for the client that made the API call.
        The request can be either authenticated using a TLS Client cert
        or an JWT in the 'Authorization' header. All POD REST and GraphQL APIs
        require authentication.

        With the TLS client cert, the reverse proxy has already validated that
        the client calling the API is the owner of the private key for the
        certificate it presented so we trust the HTTP headers set by the
        reverse proxy

        For now, we only support JWTs signed by ourselves. TODO: allow
        JWT to be signed by other members of the service. We will not support
        JWTs signed by a service as servicse should use their TLS client certs

        :param request: Starlette request instance
        :returns: (n/a)
        :raises: HTTPExceptions 400, 401, 403
        '''

        # Saveguard: only REST APIs for the POD can use class for
        # authentication
        if request.url.path.startswith(GRAPHQL_API_URL_PREFIX):
            raise HTTPException(status_code=403, detail='Not a REST API call')

        try:
            super().__init__(
                x_client_ssl_verify or TlsStatus.NONE, x_client_ssl_subject,
                x_client_ssl_issuing_ca, authorization, request.client.host
            )
        except MissingAuthInfo:
            raise HTTPException(
                status_code=401, detail='No authentication provided'
            )

        # Account cert / JWT can only be used for Pod REST APIs and, vice
        # versa, Pod REST APIs can only be called with the account cert.
        # GraphQL APIs do not call PodApRequestAuth()
        if self.id_type != IdType.ACCOUNT:
            raise HTTPException(
                status_code=403,
                detail=(
                    'Pod REST APIs can only be called with an account cert'
                    ' or account JWT'
                )
            )

        if self.auth_source == AuthSource.CERT:
            self.check_account_cert(config.server.network)

        account = config.server.account

        if self.account_id != account.account_id:
            _LOGGER.warning(
                'Authentication failure with account_id {self.account_id}'
            )
            raise HTTPException(
                status_code=401, detail='Authentication failure'
            )

        self.is_authenticated = True
