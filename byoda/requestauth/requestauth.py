'''
Helper functions for API request processing

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import logging
from enum import Enum
from os import stat
from uuid import UUID
from typing import Union

from ipaddress import ip_address as IpAddress

import jwt as py_jwt

from datetime import datetime, timezone, timedelta


from fastapi import HTTPException
import starlette

from byoda.datamodel.network import Network

from byoda.servers.directory_server import DirectoryServer
from byoda.servers.pod_server import PodServer
from byoda.servers.service_server import ServiceServer

from byoda.datatypes import IdType, EntityId
from byoda.datatypes import HttpRequestMethod
from byoda.datatypes import AuthSource

from byoda.secrets import Secret
from byoda.secrets import MemberSecret
from byoda.secrets import ServiceSecret
from byoda.secrets import MembersCaSecret
from byoda.secrets import ServiceCaSecret
from byoda.secrets import NetworkAccountsCaSecret
from byoda.secrets import NetworkRootCaSecret
from byoda.secrets import NetworkServicesCaSecret

from byoda.datatypes import TlsStatus

from byoda.exceptions import MissingAuthInfo

from byoda import config

_LOGGER = logging.getLogger(__name__)


JWT_EXPIRATION_DAYS = 365
JWT_ALGO_PREFFERED = 'RS256'
JWT_ALGO_ACCEPTED = ['RS256']


class RequestAuth():
    '''
    Three classes derive from this class:
      - AccountRequestAuthFast
      - MemberRequestAuth
      - ServiceRequestauth

    With the help of this base class they perform request authentication
    based on the M-TLS client cert passed by a reverse proxy to the
    service as HTTP headers. Each of the derived classes perform
    Request authentication based on the cert chain presented by the client
    calling the API.

    The public properties of the class are:
      - is_authenticated: Was the client successfully authenticated. The value
                          may be False if authentication was not required
      - auth_type       : AuthType instance
      - remote_addr     : the remote_addr as it connected to the reverse proxy
      - id_type         : whether the authentication was for an Account,
                          Member or Service secret
      - id              : id of either the account, member or service
      - client_cn       : the common name of the client cert
      - issuing_ca_cn   : the common name of the CA that signed the cert
      - authtoken
      - account_id      : the account_id parsed from the CN of the account cert
      - service_id      : the service_id parsed from the CN of the member or
                          service cert
      - member_id       : the member_id parsed from the CN of the member cert

    Depending on the API, the client can use one of the following for
    authentication with M-TLS:
    - account cert
    - member cert
    - service cert

    The reverse proxy in front of the server must perform TLS handshake to
    verify that the client cert has been signed by a trusted CA and it must
    set HTTP headers for the info learned from the client cert:
        X-Client-SSL-Verify
        X-Client-SSL-Subject
        X-Client-SSL-Issuing-Ca
        X-Forwarded-For

    With nginx this can be achieved by:
        listen 443 ssl;
        ssl_certificate_key /path/to/letsencrypt/private.key;
        ssl_certificate  /path/to/letsencrypt/fullchain.pem;

        ssl_verify_client optional;
        ssl_client_certificate /path/to/network-rootca-cert.pem;

        proxy_set_header X-Client-SSL-Issuing-CA $ssl_client_i_dn;
        proxy_set_header X-Client-SSL-Subject $ssl_client_s_dn;
        proxy_set_header X-Client-SSL-Verify $ssl_client_verify;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

    The uvicorn server must be run with the '--proxy-headers' setting
    to parse the X-Forwarded-For header set by nginx and present it
    to the web application as client IP
    '''

    def __init__(self, tls_status: TlsStatus,
                 client_dn: str, issuing_ca_dn: str,
                 authorization: str, remote_addr: IpAddress):
        '''
        Get the authentication info for the client that made the API call.
        As long as either the TLS client cert or the JWT from the
        Authorization checks out then we're happy. However, if the TLS client
        cert does not conform with the requirements then we return a HTTP error
        even if the Authorization header contains a valid JWT.
        If a TLS client cert is available then the reverse proxy has already
        validated that the client calling the API is the owner of the private
        key for the certificate it presented so we trust the HTTP headers set
        by the reverse proxy

        :param tls_status: instance of TlsStatus enum
        :param client_dn: designated name of the presented client TLS cert
        :param issuing_ca_dn: designated name of the issuing CA for the
        presented TLS client cert
        :param authorization: value of the Authorization header
        information in the request for authentication
        :returns: (n/a)
        :raises: MissingAuthInfo if the no authentication, AuthFailure if
        authentication was provided but is incorrect, HTTPException with
        status code 400 or 401 if malformed authentication info was provided
        '''

        self.is_authenticated: bool = False
        self.auth_source: AuthSource = AuthSource.NONE

        self.remote_addr: IpAddress = remote_addr

        self.id_type: IdType = None
        self.client_cn: str = None
        self.issuing_ca_cn: str = None
        self.token: str = None
        self.account_id: UUID = None
        self.service_id: int = None
        self.member_id: UUID = None
        self.domain: str = None

        #
        # Process the headers and if auth is 'required', throw
        # exceptions based on misformed DN/CN in certs
        #

        error = 401
        detail = 'Missing authentication info'
        if isinstance(tls_status, str):
            tls_status = TlsStatus(tls_status)

        if tls_status not in (TlsStatus.NONE, TlsStatus.SUCCESS):
            raise HTTPException(
                status_code=403, detail=f'Client TLS status is {tls_status}'
            )
        elif not tls_status:
            raise MissingAuthInfo('Missing TLS status')

        if tls_status == TlsStatus.NONE and not authorization:
            raise HTTPException(
                status_code=401,
                detail=(
                    'Either TLS client cert or Authorization '
                    'token must be provided'
                )
            )

        if (client_dn and issuing_ca_dn):
            try:
                self.authenticate_client_cert(client_dn, issuing_ca_dn)
                self.is_authenticated = True
                if self.is_authenticated:
                    self.auth_source = AuthSource.CERT
                    return
            except HTTPException as exc:
                error = exc.status_code
                detail = exc.detail

        if authorization:
            self.authenticate_authorization_header(authorization)
            if self.is_authenticated:
                self.auth_source = AuthSource.TOKEN
            return

        raise HTTPException(status_code=error, detail=detail)

    def authenticate_client_cert(self, client_dn: str, issuing_ca_dn: str):
        '''
        Authenticate the client based on the TLS client cert

        :raises: HTTPException
        '''
        self.client_cn = RequestAuth.get_commonname(client_dn)
        self.issuing_ca_cn = RequestAuth.get_commonname(issuing_ca_dn)

        if (self.client_cn == self.issuing_ca_cn or not self.issuing_ca_cn
                or self.client_cn == 'None'
                or self.issuing_ca_cn == 'None'):
            # Somehow a self-signed cert made it through the certchain
            # check
            _LOGGER.warning(
                'Misformed cert was proxied by reverse proxy, Client DN: '
                f'{client_dn}: Issuing CA DN: {issuing_ca_dn}'
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    f'Client provided a self-signed or unsigned cert: '
                    f'{client_dn}'
                )
            )

        self.id, subdomain = self.client_cn.split('.')[0:2]
        self.domain = self.client_cn.split('.', 3)[-2]
        if '-' in subdomain:
            self.service_id = subdomain.split('-')[1]

        self.id_type = RequestAuth.get_cert_idtype(self.client_cn)
        if self.id_type == IdType.ACCOUNT:
            self.account_id = self.id
        elif self.id_type == IdType.MEMBER:
            self.member_id = self.id
        elif self.is_type == IdType.SERVICE:
            pass
        else:
            raise HTTPException(
                status_code=40,
                detail=f'Unsupported ID type in  cert: {self.id_type.value}'
            )

    @staticmethod
    def authenticate_request(request: starlette.requests.Request):
        '''
        Wrapper for static RequestAuth.authenticate method

        :returns: An instance of RequestAuth
        '''
        return RequestAuth.authenticate(
            request.headers.get('X-Client-SSL-Verify'),
            request.headers.get('X-Client-SSL-Subject'),
            request.headers.get('X-Client-SSL-Issuing-CA'),
            request.headers.get('Authorization'),
            request.client.host, HttpRequestMethod(request.method)
        )

    @staticmethod
    def authenticate(tls_status: TlsStatus,
                     client_dn: str, issuing_ca_dn: str, authorization: str,
                     remote_addr: IpAddress, method: HttpRequestMethod):
        '''
        Authenticate a request based on incoming TLS headers

        Function is invoked for GraphQL APIs

        :returns: An instance of RequestAuth
        '''

        client_cn = RequestAuth.get_commonname(client_dn)
        id_type = RequestAuth.get_cert_idtype(client_cn)

        if id_type == IdType.ACCOUNT:
            from .accountrequest_auth import AccountRequestAuth
            auth = AccountRequestAuth(
                tls_status, client_dn, issuing_ca_dn, authorization,
                remote_addr, method
            )
            _LOGGER.debug('Authentication for account %s', auth.id)
        elif id_type == IdType.MEMBER:
            from .memberrequest_auth import MemberRequestAuth
            auth = MemberRequestAuth(
                tls_status, client_dn, issuing_ca_dn, authorization,
                remote_addr, method
            )
            _LOGGER.debug('Authentication for member %s', auth.id)
        elif id_type == IdType.SERVICE:
            from .servicerequest_auth import ServiceRequestAuth
            auth = ServiceRequestAuth(
                tls_status, client_dn, issuing_ca_dn, authorization,
                remote_addr, method
            )
            _LOGGER.debug('Authentication for service %s', auth.id)
        else:
            raise ValueError(
                f'Invalid authentication type in common name {client_dn}'
            )

        return auth

    def check_account_cert(self, network: Network,
                           required: bool = True) -> None:
        '''
        Checks whether the M-TLS client cert is a properly signed
        Account cert

        :raises: HttpException
        '''

        if required and not (self.client_cn and self.issuing_ca_cn):
            raise HTTPException(
                status_code=400, detail='CA-signed client cert is required'
            )

        # We verify the cert chain by creating dummy secrets for each
        # applicable CA and then review if that CA would have signed
        # the commonname found in the certchain presented by the
        # client
        try:
            # Account certs get signed by the Network Accounts CA
            entity_id = \
                NetworkAccountsCaSecret.review_commonname_by_parameters(
                    self.client_cn, network.name
                )
            self.account_id = entity_id.id

            # Network Accounts CA cert gets signed by root CA of the
            # network
            NetworkRootCaSecret.review_commonname_by_parameters(
                self.issuing_ca_cn, network.name
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail=(
                    f'Incorrect c_cn {self.client_cn} issued by '
                    f'{self.issuing_ca_cn} on network '
                    f'{network.name}'
                )
            ) from exc

        # Check that the account cert is for our account. On the directory
        # server the Account instance will be None
        account = config.server.account

        if account and account.account_id != self.account_id:
            raise HTTPException(
                status_code=403,
                detail=(
                    'Received request with cert with incorrect account_id in '
                    f'CN: {self.account_id}. Expected: {account.account_id}'
                )
            )

    def check_member_cert(self, service_id: int, network: Network) -> None:
        '''
        Checks if the M-TLS client certificate was signed the cert chain
        for members of the service
        '''

        if not self.client_cn or not self.issuing_ca_cn:
            raise HTTPException(
                status_code=401, detail='Missing MTLS client cert'
            )

        # We verify the cert chain by creating dummy secrets for each
        # applicable CA and then review if that CA would have signed
        # the commonname found in the certchain presented by the
        # client
        try:
            # Member cert gets signed by Service Member CA
            members_ca_secret = MembersCaSecret(
                None, service_id, network=network
            )
            entity_id = members_ca_secret.review_commonname(self.client_cn)
            self.member_id = entity_id.id
            self.service_id = entity_id.service_id

            # The Member CA cert gets signed by the Service CA
            service_ca_secret = ServiceCaSecret(
                None, service_id, network=network
            )
            service_ca_secret.review_commonname(self.issuing_ca_cn)
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail=(
                    f'Incorrect c_cn {self.client_cn} issued by '
                    f'{self.issuing_ca_cn} for service {service_id} on '
                    f'network {network.name}'
                )
            ) from exc

    def check_service_cert(self, network: Network, service_id: int = None
                           ) -> None:
        '''
        Checks if the MTLS client certificate was signed the cert chain
        for members of the service

        :param network: the network that we are in
        :param service_id: the service_id parsed from the incoming request,
        if applicable
        :raises: HTTPException
        '''

        if not self.client_cn or not self.issuing_ca_cn:
            raise HTTPException(
                status_code=401, detail='Missing MTLS client cert'
            )

        # Check that the client common name is well-formed and
        # extract the service_id
        entity_id = ServiceSecret.parse_commonname(self.client_cn, network)

        try:
            # Service secret gets signed by Service CA
            service_ca_secret = ServiceCaSecret(
                None, entity_id.service_id, network=network
            )
            entity_id = service_ca_secret.review_commonname(self.client_cn)
            self.service_id = entity_id.service_id

            # Service CA secret gets signed by Network Services CA
            networkservices_ca_secret = NetworkServicesCaSecret(network.paths)
            networkservices_ca_secret.review_commonname(self.issuing_ca_cn)
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail=(
                    f'Incorrect c_cn {self.client_cn} issued by '
                    f'{self.issuing_ca_cn} for service {self.service_id} on '
                    f'network {network.name}'
                )
            ) from exc

        if service_id is not None and self.service_id != service_id:
            raise HTTPException(
                status_code=403,
                detail=(
                    f'Service ID {service_id} from incoming request does not '
                    f'match service ID {self.service_id} from client cert'
                )
            )

    @staticmethod
    def get_commonname(dname: str) -> str:
        '''
        Extracts the commonname from a distinguished name in a x.509
        certificate

        :param dname: x509 distinguished name
        :returns: commonname
        :raises: ValueError if the commonname could not be extracted
        '''

        bits = dname.split(',')
        for keyvalue in bits:
            if keyvalue.startswith('CN='):
                commonname = keyvalue[(len('CN=')):]
                return commonname

        raise HTTPException(
            status_code=403,
            detail=f'Invalid format for distinguished name: {dname}'
        )

    @staticmethod
    def get_cert_idtype(commonname: str) -> IdType:
        '''
        Extracts the IdType from a distinguished name in a x.509
        certificate

        :param commonname: x509 common name
        :returns: commonname
        :raises: ValueError if the commonname could not be extracted
        '''

        commonname_bits = commonname.split('.')
        if len(commonname_bits) < 4:
            raise HTTPException(
                status_code=400,
                detail=f'Invalid common name {commonname}'
            )

        subdomain = commonname_bits[1]
        if '-' in subdomain:
            # For members, subdomain has format 'members-<service-id>'
            idtype = IdType(subdomain[:subdomain.find('-')+1])
        else:
            idtype = IdType(commonname_bits[1])

        return idtype


    @staticmethod
    def create_auth_token(issuer: str, secret: Secret, network_name: str,
                          service_id: int = None,
                          expiration_days: int = JWT_EXPIRATION_DAYS
                          ) -> bytes:
        '''
        Creates an authorization token
        '''

        expiration = (
            datetime.now(tz=timezone.utc) + timedelta(days=expiration_days)
        )

        data = {
            'exp': expiration,
            'iss': issuer,
            'aud': [f'urn:network-{network_name}'],
        }
        if service_id is not None:
            data['service_id'] = service_id

        jwt = py_jwt.encode(
            data, secret.private_key, algorithm=JWT_ALGO_PREFFERED
        )

        return jwt

    def authenticate_authorization_header(self, authorization: str):
        '''
        Check the JWT in the value for the Authorization header.

        :raises: HTTPException
        '''

        if isinstance(config.server, DirectoryServer):
            raise HTTPException(
                status_code=400, detail='Directory servers do not accept JWTs'
            )

        if not authorization or not isinstance(authorization, str):
            raise HTTPException(
                status_code=400,
                detail='No Authorization header found'
            )

        authorization = authorization.strip()
        if authorization.lower().startswith('bearer'):
            authorization = authorization[len('bearer'):]
            authorization = authorization.strip()

        # First we use the unverified JTW to find out
        # in which context we need to authenticate the client
        try:
            network = config.server.network.name
            audience = [f'urn:network-{network}']
            unverified = py_jwt.decode(
                authorization, options={'verify_signature': False},
                audience=audience, leeway=10,
                algorithms=JWT_ALGO_ACCEPTED
            )

            unverified_id = RequestAuth._parse_jwt(unverified)

            secret = RequestAuth._get_jwt_issuer_secret(unverified_id)
            if not secret.cert:
                secret.load(with_private_key=False)
        except py_jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=401, detail='JWT has expired'
            )
        except (ValueError, KeyError) as exc:
            _LOGGER.exception(f'Invalid JWT: {exc}')
            raise HTTPException(status_code=401, detail='Invalid JWT')

        if (unverified_id.id_type == IdType.ACCOUNT
                and not isinstance(config.server, PodServer)):
            raise HTTPException(
                status_code=401,
                detail=(
                    'A JWT that is signed by account cert can only be used '
                    'with the pod'
                )
            )

        if (isinstance(config.server, ServiceServer)
                and config.server.service.service_id !=
                unverified_id.service_id):
            # We are running on a service server
            raise HTTPException(
                status_code=401,
                detail=f'Invalid service_id in JWT: {unverified_id.service_id}'
            )

        # Now we have the secret for verifying the signature of the JWT
        try:
            decode_secret = secret.cert.public_key()
            py_jwt.decode(
                authorization, decode_secret, leeway=10,
                audience=audience, algorithms=JWT_ALGO_ACCEPTED
            )
            # We now know we can trust the data we earlier parsed from the JWT
            entity_id = unverified_id

            self.service_id = entity_id.service_id
            self.id_type = entity_id.id_type
            if self.service_id is not None:
                self.member_id = entity_id.id
            else:
                self.account_id = entity_id.id

            self.is_authenticated = True
            self.auth_source = AuthSource.TOKEN
        except py_jwt.exceptions.InvalidAudienceError:
            raise HTTPException(
                status_code=401, detail='JWT has incorrect audience'
            )

    @staticmethod
    def _parse_jwt(token: str) -> IdType:
        '''
        Parses the issuer, which in the form of either:
        - 'urn:member_id-<UUID>'
        - 'urn:account_id-<UUID>'
        '''

        issuer = token.get('iss')
        if not issuer:
            raise ValueError('No issuer specified in the JWT token')

        if issuer.startswith('urn'):
            issuer = issuer[4:]

        if issuer.startswith('member_id-'):
            entity_type = IdType.MEMBER
            identity = issuer[len('member_id-'):]
        elif issuer.startswith('account_id-'):
            entity_type = IdType.ACCOUNT
            identity = issuer[len('account_id-'):]
        else:
            raise ValueError(f'Invalid issuer in JWT: {issuer}')

        service_id = token.get('service_id')
        if service_id is not None:
            service_id = int(service_id)

        entity_id = EntityId(IdType(entity_type), UUID(identity), service_id)

        return entity_id

    @staticmethod
    def _get_jwt_issuer_secret(entity_id: EntityId) -> Secret:
        '''
        Gets the secret for the account or member that issued the JWT so
        that the public key for the secret can be used to verify the
        signature of the JWT.

        :param entity_id: entity parsed from the unverified JWT
        :raises: ValueError
        '''

        # This function is called before the signature of the JWT has
        # been verified so must not change any data! Nor do we want
        # to provide information to hackers submitting bogus JWTs

        if config.server.service:
            # We are running on a service server. Let's see if we have the
            # public cert of the issuer of the JWT

            if entity_id.service_id is None:
                raise ValueError('No service ID specified in the JWT')

            if entity_id.id_type == IdType.ACCOUNT:
                raise ValueError(
                    'Service API can not be called with a JWT for an account'
                )

            secret: MemberSecret = MemberSecret(
                entity_id.id, entity_id.service_id, None,
                config.server.service.network
            )
        elif config.server.account and entity_id.service_id is not None:
            # We have a JWT signed by a member of a service and we are
            # running on a pod, let's get the secret for the membership
            config.server.account.load_memberships()
            member = config.server.account.memberships.get(
                entity_id.service_id
            )
            if member:
                if member.member_id != entity_id.id:
                    raise NotImplementedError(
                        'We do not yet support JTWs signed by other members'
                    )

                secret = member.tls_secret
            else:
                # We don't want to give details in the error message as it
                # could allow people to discover which services a pod has
                # joined
                _LOGGER.exception(
                    f'Unknown service ID: {entity_id.service_id}'
                )
                raise ValueError
        elif config.server.account and entity_id.service_id is None:
            # We are running on the pod and the JWT is signed by the account
            secret = config.server.account.tls_secret
        else:
            _LOGGER.exception(
                'Could not get the secret for '
                f'{entity_id.id_type.value}{entity_id.id}'
            )
            raise ValueError

        return secret
