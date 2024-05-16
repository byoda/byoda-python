'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from typing import TypeVar
from typing import Annotated
from logging import getLogger
from byoda.util.logger import Logger

from fastapi import Request
from fastapi import WebSocket
from fastapi import Header
from fastapi import Depends
from fastapi import HTTPException

from byoda.datamodel.dataclass import SchemaDataItem

from byoda.datatypes import IdType
from byoda.datatypes import AuthSource
from byoda.datatypes import DataOperationType

from byoda.requestauth.jwt import JWT
from byoda.requestauth.requestauth import RequestAuth
from byoda.requestauth.requestauth import TlsStatus

from byoda.util.api_client.api_client import HttpMethod

from byoda.exceptions import ByodaMissingAuthInfo

from byoda import config

Network = TypeVar('Network')
Account = TypeVar('Account')
Member = TypeVar('Member')
PodServer = TypeVar('PodServer')

_LOGGER: Logger = getLogger(__name__)


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
        or an JWT in the 'Authorization' header. A

        With the TLS client cert, the reverse proxy has already validated that
        the client calling the API is the owner of the private key for the
        certificate it presented so we trust the HTTP headers set by the
        reverse proxy

        :param request: Starlette request instance
        :returns: (n/a)
        :raises: HTTPExceptions 400, 401, 403
        '''

        method: str = None
        if not isinstance(request, WebSocket):
            method = request.method

        if not request.client:
            raise HTTPException(400, 'No client information in request')

        super().__init__(request.client.host, method)

        self.tls_status: TlsStatus = TlsStatus(x_client_ssl_verify or 'NONE')
        self.client_dn: str | None = x_client_ssl_subject
        self.issuing_ca_dn: str | None = x_client_ssl_issuing_ca
        self.client_cert: str | None = x_client_ssl_cert
        self.authorization: str = authorization

    async def authenticate(self, account: Account, service_id: int = None
                           ) -> None:
        '''
        Checks whether the API is called with our account_id, or,
        if a service_id is specified, whether the API is called
        by a member of that service. In this case, checking whether
        the member is authorized to call the API is not the responsibility
        of this method

        :param service_id: the service ID for which the API was called
        '''

        try:
            jwt: JWT | None = await super().authenticate(
                self.tls_status, self.client_dn, self.issuing_ca_dn,
                self.client_cert, self.authorization
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
            member: Member = await account.get_membership(service_id)

            if not member:
                _LOGGER.warning(
                    f'Authentication failure for service {service_id}'
                    'that we are not a member of'
                )
                raise HTTPException(
                    status_code=401, detail='Authentication failure'
                )

            if self.id != member.member_id:
                _LOGGER.warning(
                    f'Authentication failure with member_id {self.id} '
                    f'does not match our member_id: {member.member_id}'
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

    async def review_data_request(self, service_id: int,
                                  class_name: str,
                                  data_op: DataOperationType,
                                  depth: int) -> bool:
        '''
        Authenticate a request to CRUD data.
        '''

        # Checks that a client cert was provided and that the cert and
        # certchain is correct
        try:
            await self.authenticate_data_request(service_id)
            self._log_auth_message()
        except Exception as exc:
            _LOGGER.debug(
                f'Authentication failed for request from {self.remote_addr}'
                f': {exc}'
            )
            raise HTTPException(
                status_code=400, detail='Authentication failed'
            )

        try:
            # Check whether the authenticated client is authorized to request
            # the data
            result = await self.authorize_data_request(
                data_op, class_name, service_id, depth
            )

            self._log_authorization_message(class_name, data_op, result)
            return result
        except Exception as exc:
            _LOGGER.exception(
                f'Authentication failed for request from {self.remote_addr}'
                f': {exc}'
            )
            raise HTTPException(
                    status_code=400,
                    detail=(
                        f'Authentication failed for {data_op.value} '
                        f'on class {class_name}'
                    )
                )

    async def authenticate_data_request(self, service_id: int) -> None:
        '''
        Authenticate a request based on incoming TLS headers or JWT

        Function is invoked for REST Data API requests

        :param request: the incoming HTTP request
        :param service_id: the ID of the service targetted by the request
        :returns: An instance of RequestAuth, unless when no authentication
        credentials were provided, in which case 'None' is returned

        :param service_id: the ID of the service
        :returns: An instance of RequestAuth or None if no credentials
        were provided
        :raises: HTTPException 400, 401 or 403
        '''

        host: str = self.remote_addr
        _LOGGER.debug(f'Authenticating Data API request from IP: {host}')

        if not self.method:
            self.method = HttpMethod('GET')

        id_type: IdType

        server: PodServer = config.server
        account: Account = server.account
        network: Network = account.network

        # Client cert, if available, sets the IdType for the authentication
        if self.client_dn and self.issuing_ca_dn:
            self.client_cn = RequestAuth.get_commonname(self.client_dn)
            id_type = RequestAuth.get_cert_idtype(self.client_cn)
        elif self.authorization:
            # Watch out, the JWT signature does not get verified here.
            jwt = await JWT.decode(
                self.authorization, None, network.name,
                download_remote_cert=False
            )
            if jwt.service_id != service_id:
                raise HTTPException(
                    status_code=401,
                    detail=(
                        f'Service ID mismatch: '
                        f'{jwt.service_id} != {service_id}'
                    )
                )

            member: Member = await account.get_membership(service_id)
            jwt.check_scope(IdType.MEMBER, member.member_id)

            id_type = jwt.issuer_type
        else:
            _LOGGER.debug('Anonymous request, no client-cert or JWT provided')
            id_type = IdType.ANONYMOUS

        if id_type == IdType.ACCOUNT:
            raise HTTPException(
                status_code=401,
                detail='Data queries should never use account credentials'
            )
        elif id_type == IdType.MEMBER:
            from byoda.requestauth.memberrequest_auth import MemberRequestAuth

            # Unfortunately, we need to create a new auth object to remain
            # compatible with MemberRequestAuth and ServiceRequestAuth so,
            # we create the new one and then copy the following attributes
            # to 'self'
            new_auth = MemberRequestAuth(self.remote_addr, self.method)
            await new_auth.authenticate(
                self.tls_status, self.client_dn, self.issuing_ca_dn,
                self.client_cert, self.authorization
            )

            # Copy the values of the new auth object to 'self'
            for key, value in vars(new_auth).items():
                setattr(self, key, value)

            _LOGGER.debug('Authentication for member %s', self.member_id)
        elif id_type == IdType.SERVICE:
            from byoda.requestauth.servicerequest_auth import \
                ServiceRequestAuth

            # Unfortunately, we need to create a new auth object to remain
            # compatible with MemberRequestAuth and ServiceRequestAuth so,
            # we create the new one and then copy the following attributes
            # to 'self'
            new_auth = ServiceRequestAuth(self.remote_addr, self.method)
            await new_auth.authenticate(
                self.tls_status, self.client_dn, self.issuing_ca_dn,
                self.client_cert, self.authorization
            )

            # Copy the values of the new auth object to 'self'
            for key, value in vars(new_auth).items():
                setattr(self, key, value)

            _LOGGER.debug(
                f'Authentication for service f{self.service_id}: '
                f'{self.is_authenticated}'
            )
        elif id_type == IdType.ANONYMOUS:
            self.is_authenticated = False
            self.id_type = IdType.ANONYMOUS
        else:
            raise ValueError(
                f'Invalid authentication type in common name {self.client_dn}'
            )

        if self.is_authenticated and self.service_id != service_id:
            raise HTTPException(
                status_code=401,
                detail=f'credential is not for service {service_id}'
            )

    async def authorize_data_request(self, operation: DataOperationType,
                                     class_name: str, service_id: int,
                                     depth: int) -> bool:
        '''
        Checks the authorization of a Data REST request for a service.
        It is called by the code generated from the Jinja
        templates implementing the Data API support
        '''

        _LOGGER.debug(
            f'Authorizing Data API request for operation {operation.value} on '
            f'data class {class_name} for service {service_id}'
        )

        # We need to review whether the requestor is authorized to access
        # the data in the request
        account: Account = config.server.account
        member: Member = await account.get_membership(service_id)

        if not member:
            # We do not want to expose whether the account is a member of
            # a service. Such requests should not happen as requests must
            # be sent to the membership-FQDN but this is an additional
            # safeguard
            raise HTTPException(status_code=401, detail='Access denied')

        # data_classes contain the access permissions for the class
        data_classes: list[SchemaDataItem] = member.schema.data_classes

        if class_name not in data_classes:
            raise ValueError(
                f'Request for data element {class_name} that is not included '
                'at the root level of the service contract'
            )

        _LOGGER.debug(f'Authorizing request for data element {class_name}')

        data_class: SchemaDataItem = data_classes[class_name]
        access_allowed = await data_class.authorize_access(
            operation, self, service_id, depth
        )

        if access_allowed is None:
            # If no access controls were defined at all in the schema (which
            # should never be the case) then only the pod membership has access
            if (self.id_type == IdType.MEMBER
                    and self.member_id == member.member_id and
                    operation == DataOperationType.READ):
                access_allowed = True
                _LOGGER.debug('Allowing default access to read for pod member')
            else:
                access_allowed = False
                _LOGGER.debug('Blocking default access')

        return access_allowed

    def _log_auth_message(self) -> None:
        '''
        Log a message about the result of the authentication

        :returns: (none)
        '''
        if self.id_type == IdType.MEMBER:
            _LOGGER.debug(
                f'Authentication for member {self.member_id}: '
                f'{self.is_authenticated}'
            )
        elif self.id_type == IdType.ANONYMOUS:
            _LOGGER.debug(
                f'Authentication for anonymous user: '
                f'{self.is_authenticated}'
            )
        elif self.id_type == IdType.APP:
            _LOGGER.debug(
                f'Authentication for app {self.id}: {self.is_authenticated}'
            )
        elif self.id_type == IdType.SERVICE:
            _LOGGER.debug(
                f'Authentication for service {self.service_id}: '
                f'{self.is_authenticated}'
            )
        else:
            raise HTTPException(f'Unknown ID type: {self.id_type}')

    def _log_authorization_message(self, class_name: str,
                                   data_op: DataOperationType,
                                   result: bool) -> None:
        '''
        Log a message with info about the authorization result

        :param class_name: the authorized class
        :param data_op: the authorized data operation
        :returns: (none)
        '''

        if self.id_type == IdType.MEMBER:
            _LOGGER.debug(
                f'Authorization for member {self.member_id}: '
                f'for {data_op.value} on {class_name}: {result}'
            )
        elif self.id_type == IdType.ANONYMOUS:
            _LOGGER.debug(
                f'Authorization for anonymous user: '
                f'{result}'
            )
        if self.id_type == IdType.APP:
            _LOGGER.debug(
                f'Authorization for app {self.app_id}: '
                f'for {data_op.value} on {class_name}: {result}'
            )
        else:
            _LOGGER.debug(
                f'Authorization for service {self.service_id}: '
                f'for {data_op.value} on {class_name}: {result}'
            )


class PodApiWebSocketAuth(PodApiRequestAuth):
    def __init__(self,
                 websocket: WebSocket,
                 x_client_ssl_verify: TlsStatus | None = Header(None),
                 x_client_ssl_subject: str | None = Header(None),
                 x_client_ssl_issuing_ca: str | None = Header(None),
                 x_client_ssl_cert: str | None = Header(None),
                 authorization: str | None = Header(None)):
        '''
        Get the authentication info for the client that made the API call.
        The request can be either authenticated using a TLS Client cert
        or an JWT in the 'Authorization' header.

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

        super().__init__(
            websocket, x_client_ssl_verify, x_client_ssl_subject,
            x_client_ssl_issuing_ca, x_client_ssl_cert, authorization
        )


AuthDep = Annotated[PodApiRequestAuth, Depends(PodApiRequestAuth)]


AuthWsDep = Annotated[PodApiWebSocketAuth, Depends(PodApiWebSocketAuth)]
