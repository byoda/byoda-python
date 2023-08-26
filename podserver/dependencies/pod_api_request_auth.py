'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from typing import TypeVar
from typing import Annotated

from fastapi import Header, HTTPException, Request
from fastapi import Depends

from byoda.datamodel.member import GRAPHQL_API_URL_PREFIX
from byoda.datatypes import AuthSource, IdType

from byoda.requestauth.requestauth import RequestAuth, TlsStatus
from byoda.exceptions import ByodaMissingAuthInfo

from byoda import config

Member = TypeVar('Member')
PodServer = TypeVar('PodServer')

_LOGGER = logging.getLogger(__name__)


class PodApiRequestAuth(RequestAuth):
    def __init__(self,
                 request: Request,
                 x_client_ssl_verify: TlsStatus | None = Header(None),
                 x_client_ssl_subject: str | None = Header(None),
                 x_client_ssl_issuing_ca: str | None = Header(None),
                 x_client_ssl_cert: str | None = Header(None),
                 authorization: str | None = Header(None)):
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

        # Saveguard: only REST APIs for the POD can use this class for
        # authentication
        if request.url.path.startswith(GRAPHQL_API_URL_PREFIX):
            raise HTTPException(status_code=403, detail='Not a REST API call')

        super().__init__(request.client.host, request.method)

        self.x_client_ssl_verify: TlsStatus | None = x_client_ssl_verify
        self.x_client_ssl_subject: str | None = x_client_ssl_subject
        self.x_client_ssl_issuing_ca: str | None = x_client_ssl_issuing_ca
        self.x_client_ssl_cert: str | None = x_client_ssl_cert
        self.authorization = authorization

    async def authenticate(self, service_id: int = None):
        '''
        Checks whether the API is called with our account_id, or,
        if a service_id is specified, whether the API is called
        by a member of that service. In this case, checking whether
        the member is authorized to call the API is not the responsibility
        of this method

        :param service_id: the service ID for which the API was called
        '''

        try:
            jwt = await super().authenticate(
                self.x_client_ssl_verify or TlsStatus.NONE,
                self.x_client_ssl_subject,
                self.x_client_ssl_issuing_ca,
                self.x_client_ssl_cert,
                self.authorization
            )
        except ByodaMissingAuthInfo:
            raise HTTPException(
                status_code=401, detail='No authentication provided'
            )

        if service_id is None:
            id_type = IdType.ACCOUNT
        else:
            id_type = IdType.MEMBER

        if self.id_type != id_type:
            raise HTTPException(
                status_code=403,
                detail=(
                    'This pod REST API can only be called with a '
                    f'cert or a JWT for a {id_type.value}'
                )
            )

        server: PodServer = config.server
        account = server.account

        if self.id_type == IdType.ACCOUNT:
            if self.auth_source == AuthSource.CERT:
                self.check_account_cert(config.server.network)
            else:
                jwt.check_scope(IdType.ACCOUNT, account.account_id)

            if self.account_id != account.account_id:
                _LOGGER.warning(
                    'Authentication failure with account_id {self.account_id}'
                )
                raise HTTPException(
                    status_code=401, detail='Authentication failure'
                )
        elif self.id_type == IdType.MEMBER:
            await account.load_memberships()
            member: Member = account.memberships.get(service_id)

            if not member:
                _LOGGER.warning(
                    f'Authentication failure for service {service_id}'
                    'that we are not a member of'
                )
                raise HTTPException(
                    status_code=401, detail='Authentication failure'
                )

            if self.auth_source == AuthSource.CERT:
                self.check_member_cert(service_id, config.server.network)
            else:
                jwt.check_scope(IdType.MEMBER, member.member_id)
        else:
            raise HTTPException(
                status_code=400, detail='Invalid id type in JWT'
            )

        self.is_authenticated = True


AuthDep = Annotated[PodApiRequestAuth, Depends(PodApiRequestAuth)]
