'''
Helper functions for API request processing

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license
'''

from uuid import UUID
from typing import TypeVar
from logging import getLogger
from ipaddress import ip_address as IpAddress

from fastapi import HTTPException

from jwt.exceptions import ExpiredSignatureError
from jwt.exceptions import InvalidAudienceError
from jwt.exceptions import InvalidSignatureError
from jwt.exceptions import PyJWTError

from byoda.datamodel.network import Network

from byoda.datatypes import IdType
from byoda.datatypes import AuthSource
from byoda.datatypes import TlsStatus
from byoda.datatypes import EntityId

from byoda.secrets.secret import Secret
from byoda.secrets.service_secret import ServiceSecret
from byoda.secrets.membersca_secret import MembersCaSecret
from byoda.secrets.appsca_secret import AppsCaSecret
from byoda.secrets.serviceca_secret import ServiceCaSecret
from byoda.secrets.networkaccountsca_secret import NetworkAccountsCaSecret
from byoda.secrets.networkrootca_secret import NetworkRootCaSecret
from byoda.secrets.networkservicesca_secret import NetworkServicesCaSecret

from byoda.servers.server import Server

from byoda.util.api_client.api_client import HttpMethod

from byoda.exceptions import ByodaMissingAuthInfo

from byoda.util.logger import Logger

from byoda import config

from .jwt import JWT

_LOGGER: Logger = getLogger(__name__)

Account = TypeVar('Account')
Member = TypeVar('Member')


class RequestAuth:
    '''
    Class to authenticate REST API and Data API calls

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
        X-Client-SSL-Cert
        X-Forwarded-For

    With angie this can be achieved by:
        listen 443 ssl;
        ssl_certificate_key /path/to/unencrypted/private.key;
        ssl_certificate  /path/to/fullchain.pem;

        ssl_verify_client optional;
        ssl_client_certificate /path/to/network-rootca-cert.pem;

        proxy_set_header X-Client-SSL-Issuing-CA $ssl_client_i_dn;
        proxy_set_header X-Client-SSL-Subject $ssl_client_s_dn;
        proxy_set_header X-Client-SSL-Verify $ssl_client_verify;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

    The uvicorn server must be run with the '--proxy-headers' setting
    to parse the X-Forwarded-For header set by angie and present it
    to the web application as client IP
    '''

    def __init__(self, remote_addr: IpAddress, method: HttpMethod) -> None:
        '''
        constructor

        :param remote_addr: IP address of the caller
        '''

        self.is_authenticated: bool = False
        self.auth_source: AuthSource = AuthSource.NONE

        self.remote_addr: IpAddress = remote_addr
        self.id_type: IdType = IdType.ANONYMOUS

        # HttpMethod is None when request is from a websockets
        self.method: HttpMethod
        if isinstance(method, HttpMethod):
            self.method = method
        elif method:
            self.method = HttpMethod(method.lower())
        else:
            self.method = 'get'

        self.client_cn: str | None = None
        self.issuing_ca_cn: str | None = None
        self.token: str | None = None
        self.account_id: UUID | None = None
        self.service_id: int | None = None
        self.member_id: UUID | None = None
        self.domain: str | None = None

        self.id: UUID | None = None

        self.tls_status: TlsStatus | None = None
        self.client_dn: str | None = None
        self.issuing_ca_dn: str | None = None
        self.authorization: str | None = None
        self.jwt: JWT | None = None

        self.log_extra: dict[str, str] = {
            'remote_addr': remote_addr,
            'is_authenticated': self.is_authenticated,
            'method': method,
        }

    async def authenticate(self, tls_status: TlsStatus, client_dn: str | None,
                           issuing_ca_dn: str | None, client_cert: str | None,
                           authorization: str | None) -> JWT | None:
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
        :param client_cert: PEM url-encoded client TLS cert
        :param authorization: value of the HTTP Authorization header
        :returns: if authenticated with an authorization header, the JWT is
        returned
        :raises: ByodaMissingAuthInfo if the no authentication, AuthFailure if
        authentication was provided but is incorrect, HTTPException with
        status code 400 or 401 if malformed authentication info was provided

        Process the headers and if auth is 'required', throw
        exceptions based on misformed DN/CN in certs

        :param authorization: value of the Authorization header
        information in the request for authentication
        '''

        self.tls_status: TlsStatus | None = tls_status
        self.client_dn: str | None = client_dn
        self.issuing_ca_dn: str | None = issuing_ca_dn
        self.client_cert: str | None = client_cert
        self.authorization: str | None = authorization

        error: int = 401
        detail: str = 'Missing authentication info'
        if self.tls_status is None:
            self.tls_status = TlsStatus.NONE
        elif isinstance(tls_status, str):
            self.tls_status = TlsStatus(self.tls_status)

        self.log_extra['tls_status'] = self.tls_status,

        if self.tls_status not in (TlsStatus.NONE, TlsStatus.SUCCESS):
            _LOGGER.debug('Auth failure: TLS status', extra=self.log_extra)
            raise HTTPException(
                status_code=403,
                detail=f'Client TLS status is {self.tls_status}'
            )

        if self.tls_status == TlsStatus.NONE and not self.authorization:
            _LOGGER.debug('No credentials provided', extra=self.log_extra)
            raise ByodaMissingAuthInfo('No credentials provided')

        if client_dn:
            try:
                _LOGGER.debug(
                    'Authenticating using client cert', extra=self.log_extra
                )
                self.authenticate_client_cert(
                    self.client_dn, self.issuing_ca_dn
                )
                self.auth_source = AuthSource.CERT
                self.log_extra['auth_source'] = self.auth_source
                return
            except HTTPException as exc:
                error = exc.status
                detail = exc.detail

        if self.authorization:
            _LOGGER.debug('Authenticating using JWT', extra=self.log_extra)
            jwt: JWT = await self.authenticate_authorization_header(
                self.authorization
            )
            self.auth_source = AuthSource.TOKEN
            self.log_extra['auth_source'] = self.auth_source
            return jwt

        raise HTTPException(status_code=error, detail=detail)

    def authenticate_client_cert(self, client_dn: str, issuing_ca_dn: str
                                 ) -> None:
        '''
        Authenticate the client based on the TLS client cert

        :raises: HTTPException
        '''
        self.client_cn = RequestAuth.get_commonname(client_dn)
        self.issuing_ca_cn = RequestAuth.get_commonname(issuing_ca_dn)

        self.log_extra['client_cn'] = self.client_cn
        self.log_extra['issuing_ca_cn'] = self.issuing_ca_cn

        if (self.client_cn == self.issuing_ca_cn or not self.issuing_ca_cn
                or self.client_cn == 'None'
                or self.issuing_ca_cn == 'None'):
            # Somehow a self-signed cert made it through the certchain
            # check
            _LOGGER.warning(
                'Misformed cert was proxied by reverse proxy, Client DN: ',
                extra=self.log_extra
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    f'Client provided a self-signed or unsigned cert: '
                    f'{client_dn}'
                )
            )

        subdomain: str
        self.id, subdomain = self.client_cn.split('.')[0:2]
        self.domain = self.client_cn.split('.', 3)[-2]
        if '-' in subdomain:
            self.service_id = subdomain.split('-')[1]

        self.id_type = RequestAuth.get_cert_idtype(self.client_cn)
        self.log_extra['id_type'] = self.id_type
        if self.id_type == IdType.ACCOUNT:
            _LOGGER.debug(
                'Authenticating client cert for an account',
                extra=self.log_extra
            )
            self.account_id = self.id
        elif self.id_type == IdType.MEMBER:
            _LOGGER.debug(
                'Authenticating client cert for a member',
                extra=self.log_extra
            )
            self.member_id = self.id
        elif self.id_type == IdType.SERVICE:
            _LOGGER.debug(
                'Authenticating client cert for a service',
                extra=self.log_extra
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f'Unsupported ID type in cert: {self.id_type.value}'
            )

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
            entity_id: EntityId = \
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
        account: Account = config.server.account

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
                service_id, network=network
            )
            entity_id: EntityId = members_ca_secret.review_commonname(
                self.client_cn
            )
            self.member_id = entity_id.id
            self.id = self.member_id
            self.service_id = entity_id.service_id

            # The Member CA cert gets signed by the Service CA
            service_ca_secret = ServiceCaSecret(service_id, network=network)
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

    def check_service_cert(self, network: Network) -> None:
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
                entity_id.service_id, network=network
            )
            entity_id: EntityId = service_ca_secret.review_commonname(
                self.client_cn
            )
            self.service_id = entity_id.service_id
            self.id = self.service_id

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

    def check_app_cert(self, service_id: int, network: Network) -> None:
        '''
        Checks if the M-TLS client certificate was signed using the cert chain
        for apps of the service
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
            apps_ca_secret = AppsCaSecret(
                service_id, network=network
            )
            entity_id: EntityId = apps_ca_secret.review_commonname(
                self.client_cn
            )
            self.member_id = entity_id.id
            self.id = self.member_id
            self.service_id = entity_id.service_id

            # The App CA cert gets signed by the Service App CA
            apps_ca_secret = AppsCaSecret(service_id, network=network)
            apps_ca_secret.review_commonname(self.issuing_ca_cn)
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail=(
                    f'Incorrect c_cn {self.client_cn} issued by '
                    f'{self.issuing_ca_cn} for service {service_id} on '
                    f'network {network.name}'
                )
            ) from exc

    @staticmethod
    def get_commonname(dname: str) -> str:
        '''
        Extracts the commonname from a distinguished name in a x.509
        certificate

        :param dname: x509 distinguished name
        :returns: commonname
        :raises: ValueError if the commonname could not be extracted
        '''

        bits: list[str] = dname.split(',')
        for keyvalue in bits:
            if keyvalue.startswith('CN='):
                commonname: str = keyvalue[(len('CN=')):]
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
        :returns: one of the IdType values
        :raises: ValueError if the commonname could not be extracted
        '''

        commonname_bits: list[str] = commonname.split('.')
        if len(commonname_bits) < 4:
            raise HTTPException(
                status_code=400,
                detail=f'Invalid common name {commonname}'
            )

        subdomain: str = commonname_bits[1]
        if '-' in subdomain:
            # For members, subdomain has format 'members-<service-id>'
            idtype = IdType(subdomain[:subdomain.find('-')+1])
        else:
            idtype = IdType(commonname_bits[1])

        return idtype

    async def authenticate_authorization_header(self, authorization: str
                                                ) -> JWT:
        '''
        Check the JWT in the value for the Authorization header.

        :raises: HTTPException
        '''

        server: Server = config.server
        network: Network = server.network

        if not server.accepts_jwts():
            raise HTTPException(
                status_code=400,
                detail='Only Pods, app servers and service servers accept JWTs'
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

        # First we use the unverified JWT to find out
        # in which context we need to authenticate the client
        try:
            unverified_jwt: JWT = await JWT.decode(
                authorization, None, network.name, download_remote_cert=False
            )

            secret: Secret = await unverified_jwt._get_issuer_secret()
            # TODO: next 2 lines can be removed?
            if not secret.cert:
                await secret.load(with_private_key=False)
        except ExpiredSignatureError:
            raise HTTPException(
                status_code=401, detail='JWT has expired'
            )
        except (ValueError, KeyError) as exc:
            _LOGGER.exception(f'Invalid JWT: {exc}')
            raise HTTPException(status_code=401, detail='Invalid JWT')

        # Now we have the secret for verifying the signature of the JWT
        try:
            await JWT.decode(authorization, secret, network.name)

            # We now know we can trust the data we earlier parsed from the JWT
            jwt: JWT = unverified_jwt

            self.service_id = jwt.service_id
            self.id_type = jwt.issuer_type
            if self.service_id is not None:
                self.member_id = jwt.issuer_id
                self.id = jwt.issuer_id
            else:
                self.account_id = jwt.issuer_id
                self.id = self.account_id

            self.auth_source = AuthSource.TOKEN
            return jwt
        except InvalidAudienceError:
            raise HTTPException(
                status_code=401, detail='JWT has incorrect audience'
            )
        except InvalidSignatureError:
            raise HTTPException(
                status_code=403, detail='JWT signature invalid'
            )
        except PyJWTError as exc:
            raise HTTPException(status_code=401, detail=f'JWT error: {exc}')
