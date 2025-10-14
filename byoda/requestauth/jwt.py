'''
Class for creation and verification of JWTs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from uuid import UUID
from typing import Self
from typing import TypeVar

from logging import Logger
from logging import getLogger
from datetime import UTC
from datetime import datetime
from datetime import timedelta

import jwt as py_jwt

from opentelemetry.trace import get_tracer
from opentelemetry.sdk.trace import Tracer

from byoda.secrets.secret import Secret

from byoda.datatypes import IdType
from byoda.datatypes import ServerType

from byoda import config

_LOGGER: Logger = getLogger(__name__)
TRACER: Tracer = get_tracer(__name__)

ServiceServer = TypeVar('ServiceServer')
PodServer = TypeVar('PodServer')
AppServer = TypeVar('AppServer')
Service = TypeVar('Service')

JWT_EXPIRATION_DAYS = 365
JWT_ALGO_PREFFERED = 'RS256'
JWT_ALGO_ACCEPTED: list[str] = ['RS256']


class JWT:
    def __init__(self, network_name: str) -> None:
        self.expiration: datetime = None
        self.issuer: str = None
        self.issuer_id: UUID = None
        self.issuer_type: IdType = None

        # Audience is a JWT field that must match expected audience
        # when decoding a JWT.
        self.audience: list[str] = [f'urn: network-{network_name}']

        # The scope is a data field that we add that the receiving
        # entity must match with its own ID(s) to see if the JWT
        # is intended for use with itself
        self.scope: list[str] | None = None

        # Who should accept this JWT for authentication?
        self.scope_type: IdType | None = None
        self.scope_id: UUID | int

        self.secret: Secret = None
        self.service_id: int = None

        self.encoded: str | None = None
        self.decoded: dict[str:str] | None = None
        self.verified: bool | None = None

        self.network_name: str = network_name

    @staticmethod
    @TRACER.start_as_current_span('JWT.create')
    def create(identifier: UUID, id_type: IdType, secret: Secret,
               network_name: str, service_id: int | None,
               scope_type: IdType, scope_id: UUID | int,
               expiration_seconds: int = JWT_EXPIRATION_DAYS * 24 * 60 * 60
               ) -> Self:
        '''
        Factory for authorization tokens

        :param identifier: the account_id or member_id that will sign the JWT
        :param id_type: whether the JWT will be used to authenticate
        against the account or member of the pod or against a service or
        app server
        :param secret: the secret from which the private key will be used
        to sign the JWT
        :param network_name: the name of the network that the JWT is valid in
        :param service_id: the service_id of the service that the JWT is valid
        for
        :param scope_id: the id of the target that the JWT is valid for. BUG:
        we really mean audience ID here, ie. service_id or app_id
        :param scope_type: the IdType that the JWT is valid for: BUG:
        we really mean audience type here, ie. service or app
        :param expiration_seconds:
        for
        :returns: the JWT
        :raises: ValueError
        '''

        _LOGGER.debug('Creating a JWT')
        jwt = JWT(network_name)

        jwt.scope = JWT.generate_scope(
            scope_id, scope_type, service_id, network_name
        )

        if id_type == IdType.ACCOUNT:
            jwt.issuer_id = f'account_id-{identifier}'
        elif id_type == IdType.MEMBER:
            jwt.issuer_id = f'member_id-{identifier}'
        else:
            raise ValueError(f'Invalid id_type: {id_type}')

        if scope_type == IdType.SERVICE:
            jwt.audience = [JWT.get_audience(network_name, service_id)]
        elif scope_type == IdType.APP:
            jwt.audience = [
                JWT.get_audience(network_name, service_id, scope_id)
            ]
        else:
            # We use value for audience as set by constructor
            pass

        jwt.issuer_type = id_type

        jwt.service_id = service_id

        jwt.scope_type = scope_type
        jwt.scope_id = scope_id

        jwt.secret = secret

        jwt.expiration = (
            datetime.now(tz=UTC) + timedelta(seconds=expiration_seconds)
        )
        jwt.encode()

        _LOGGER.debug(f'Generated JWT with audience: {jwt.audience}')
        return jwt

    @staticmethod
    def generate_scope(scope_id: UUID | int, scope_type: IdType,
                       service_id: int, network_name: str) -> list[str]:
        '''
        Generate a value for the audience field of the JWT.

        :param network_name: the name of the network that the JWT is valid in
        :param service_id: the service_id of the service that the JWT is valid
        for
        :param audience_id: the id of the audience that the JWT is valid for
        :param audience_type: the type of the audience that the JWT is valid
        for
        '''

        scope: str = f'urn: {scope_id}.{scope_type.value}'
        if service_id:
            scope += f'{service_id}'

        scope += f'.{network_name}'

        return scope

    def parse_scope(self, network_name: str) -> None:
        '''
        Parses a string generated by JWT.generate_scope_value() and
        checks the parsed data against the data already parsed from the JWT.

        :param scope: string to parse
        :param network_name: name of the network
        :raises: ValueError if the scope does not match the expected format
        or does not match the data already parsed from the JWT
        '''

        if self.scope.startswith('urn:'):
            self.scope = self.scope[4:].strip()

        hostname: str
        subdomain: str
        domain: str
        hostname, subdomain, domain = self.scope.split('.', maxsplit=2)
        if domain != network_name:
            raise ValueError(f'Network {domain} does not equal {network_name}')

        if '-' in subdomain:
            id_type_value: str
            service_id_val: str
            id_type_value, service_id_val = subdomain.split('-')
            if int(service_id_val) != self.service_id:
                raise ValueError(
                    f'Service id {service_id_val} does '
                    f'not equal {self.service_id}'
                )
            self.scope_type = IdType(f'{id_type_value}-')
        else:
            self.scope_type = IdType(subdomain)

        if self.scope_type == IdType.SERVICE:
            self.scope_id = int(hostname)
        else:
            self.scope_id = UUID(hostname)

    def check_scope(self, scope_type: IdType, scope_id: UUID | int) -> None:
        '''
        Check whether the JWT was intended to be used for authenticating
        against us

        :param jwt: the JWT to check
        :param network: the network that we are in
        :raises: HTTPException
        '''

        if self.scope_type != scope_type:
            raise ValueError(
                f'JWT does not match our scope type: {scope_type}'
            )

        if self.scope_id != scope_id:
            raise ValueError(f'JWT does not match our scope ID: {scope_id}')

    @TRACER.start_as_current_span('JWT.encode')
    def encode(self) -> str:
        data: dict[str, str | list[str] | datetime | UUID] = {
            'exp': self.expiration,
            'iss': f'urn: {self.issuer_id}',
            'aud': self.audience,
            'scope': self.scope,
        }
        if self.service_id is not None:
            data['service_id'] = self.service_id

        jwt: str = py_jwt.encode(
            data, self.secret.private_key, algorithm=JWT_ALGO_PREFFERED
        )
        self.verified = True

        self.encoded = jwt

        return self.encoded

    @staticmethod
    def get_audience(network_name: str, service_id: int | None = None,
                     app_id: UUID | None = None) -> str:
        '''
        Get the audience for a JWT

        :param network_name: the name of the network that the JWT is valid in
        :param service_id: the service_id of the service that the JWT is valid
        for
        :param app_id: the app_id of the app that the JWT is valid for
        :returns: the audience
        '''

        if service_id is not None:
            aud: str = f'urn:network-{network_name}:service-{service_id}'
            if app_id:
                aud += f':app-{app_id}'
            return aud
        else:
            return f'urn: network-{network_name}'

    @staticmethod
    @TRACER.start_as_current_span(name='JWT.decode')
    async def decode(authorization: str, secret: Secret | None,
                     network_name: str, download_remote_cert: bool = True
                     ) -> Self:
        '''
        Decode an encoded JWT with or without verification.

        :param authorization: the encoded JWT
        :param secret: verification will not be performed if None is specified
        :param network_name: the name of the network that the JWT is valid in
        :param service_id: the service_id of the service that the JWT is valid
        for, will be None for decoding account JWTs
        :param identifier: Identity of the server decoding the JWT
        :param id_type: the type of entity decoding the JWT
        :param download_remote_cert: should remote cert be downloaded to verify
        the signature of the JWT? The value for this parameter is ignored when
        a value for the 'secret' parameter is provided
        :raises: ValueError, FileNotFound
        :returns: JWT
        '''

        server: PodServer | ServiceServer | AppServer = config.server

        if authorization.lower().startswith('bearer'):
            authorization = authorization[len('bearer'):]

        authorization = authorization.strip()

        audience: str
        if server.server_type in (ServerType.SERVICE, ServerType.APP):
            service: Service = server.service
            audience = JWT.get_audience(
                network_name, service.service_id, server.app_id
            )
        else:
            audience = JWT.get_audience(network_name)

        if secret:
            data: dict[str, any] = py_jwt.decode(
                authorization, secret.cert.public_key(), leeway=10,
                audience=audience, algorithms=JWT_ALGO_ACCEPTED
            )
            verified = True
        else:
            # Decode without verification of the signature
            data = py_jwt.decode(
                authorization, leeway=10, audience=audience,
                algorithms=JWT_ALGO_ACCEPTED,
                options={'verify_signature': False}
            )
            verified = False

        jwt = JWT(data['aud'])

        jwt.verified = verified

        jwt.expiration = data['exp']
        jwt.issuer = data.get('iss')
        if not jwt.issuer:
            raise ValueError('No issuer specified in the JWT')

        if jwt.issuer.startswith('urn:'):
            jwt.issuer = jwt.issuer[4:].strip()
        else:
            raise ValueError('JWT issuer does not start with "urn:"')

        if jwt.issuer.startswith('member_id-'):
            jwt.issuer_type = IdType.MEMBER
            jwt.issuer_id = UUID(jwt.issuer[len('member_id-'):])
        elif jwt.issuer.startswith('account_id-'):
            jwt.issuer_type = IdType.ACCOUNT
            jwt.issuer_id = UUID(jwt.issuer[len('account_id-'):])
        else:
            raise ValueError(f'Invalid issuer in JWT: {jwt.issuer}')

        jwt.audience = data['aud']

        if not isinstance(jwt.audience, list):
            jwt.audience = [jwt.audience]

        if len(jwt.audience) != 1:
            raise ValueError(
                f'Invalid audience targets in JWT {len(jwt.audience)}'
            )

        if audience not in jwt.audience:
            raise ValueError(
                f'Invalid audience in JWT: {audience} not in {jwt.audience}'
            )

        jwt.service_id = data.get('service_id')
        if jwt.service_id is not None:
            jwt.service_id = int(jwt.service_id)

        jwt.scope = data.get('scope')
        jwt.parse_scope(network_name)

        if not secret and download_remote_cert:
            # Get the secret, if necessary from remote pod
            secret = await jwt._get_issuer_secret()

            # Now that we have the secret, verify the signature by decoding
            # the Authorization header again
            py_jwt.decode(
                authorization, secret.cert.public_key(), leeway=10,
                audience=audience, algorithms=JWT_ALGO_ACCEPTED
            )
            jwt.verified = True

        jwt.secret = secret

        return jwt

    def as_header(self) -> dict[str, str]:
        '''
        Return the JWT as a dict for the HTTP header value for use
        in HTTP requests

        :returns: the JWT as a header value
        '''

        return {'Authorization': self.as_auth_token()}

    def as_auth_token(self) -> str:
        '''
        Return the JWT as a dict for the HTTP header value for use
        in HTTP requests

        :returns: the JWT as a string for authentication in a HTTP request
        '''

        return f'bearer {self.encoded}'

    async def _get_issuer_secret(self) -> Secret:
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

        await config.server.review_jwt(self)
        secret: Secret = await config.server.get_jwt_secret(self)

        if not secret:
            _LOGGER.exception(
                f'Could not get the secret for {self.id_type.value}{self.id}'
            )
            raise ValueError

        return secret
