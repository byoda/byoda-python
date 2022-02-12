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
from byoda.datatypes import IdType

from byoda.requestauth.requestauth import RequestAuth, TlsStatus
from byoda.exceptions import MissingAuthInfo

from byoda import config


_LOGGER = logging.getLogger(__name__)


class PodRequestAuth(RequestAuth):
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
        or an JWT in the Authentication header.

        With the TLS client cert, the reverse proxy has already validated that
        the client calling the API is the owner of the private key for the
        certificate it presented so we trust the HTTP headers set by the
        reverse proxy

        For now, we only support JWTs signed by ourself. TODO: allow
        JWT to be signed by other members of the service. We will not support
        JWTs signed by a service as servicse should use their TLS client certs

        :param request: Starlette request instance
        :returns: (n/a)
        :raises: HTTPExceptions 400, 401, 403
        '''

        try:
            super().__init__(
                x_client_ssl_verify or TlsStatus.NONE, x_client_ssl_subject,
                x_client_ssl_issuing_ca, authorization, request.client.host
            )
        except MissingAuthInfo:
            raise HTTPException(
                status_code=400, detail='No authentication provided'
            )

        # Account cert can only be used for Pod REST APIs and, vice versa,
        # Pod REST APIs can only be called with the account cert
        # TODO: SECURITY. Hardcoding URLs outside their code base is baaad
        if request.url.path.startswith('/api/v1/pod'):
            if self.id_type != IdType.ACCOUNT:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        'Pod REST APIs can only be called with an account cert'
                    )
                )
        else:
            if self.id_type == IdType.ACCOUNT:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        'Only Pod REST APIs can be called with an account cert'
                    )
                )

        # This API can be called by ourselves, someone in our network for
        # the service, the service or an approved application of the service
        if self.id_type == IdType.ACCOUNT:
            # if service_id:
            #    raise HTTPException(
            #        status_code=400,
            #        detail=(
            #            'Service ID specified for request authenticated '
            #            'with an account secret'
            #        )
            #    )
            self.check_account_cert(config.server.network)
        elif self.id_type == IdType.MEMBER:
            self.check_member_cert(service_id, config.server.network)
        elif self.id_type == IdType.SERVICE:
            url_path = request.url.path
            if not url_path.startswith(GRAPHQL_API_URL_PREFIX):
                raise HTTPException(
                    status_code=403,
                    detail=(
                        'Service credentials can not be used for API '
                        f'{url_path}'
                    )
                )

            try:
                service_id = int(url_path[len(GRAPHQL_API_URL_PREFIX):])
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f'Invalid GraphQL API path: {url_path}'
                )
            self.check_service_cert(config.server.network, service_id)
        else:
            raise HTTPException(
                status_code=400, detail=f'Unknown IdType: {self.id_type}'
            )

        self.is_authenticated = True
