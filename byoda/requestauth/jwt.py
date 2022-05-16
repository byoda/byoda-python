'''
Wrapper class for the PyJWT module

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import logging
from uuid import UUID

import jwt as py_jwt


from datetime import datetime, timezone, timedelta

from byoda.servers.service_server import ServiceServer
from byoda.servers.pod_server import PodServer

from byoda.secrets import Secret
from byoda.secrets import MemberSecret

from byoda.datatypes import IdType

from byoda import config

_LOGGER = logging.getLogger(__name__)


JWT_EXPIRATION_DAYS = 365
JWT_ALGO_PREFFERED = 'RS256'
JWT_ALGO_ACCEPTED = ['RS256']


class JWT:
    def __init__(self, network_name: str):
        self.expiration: datetime = None
        self.issuer: str = None
        self.issuer_id: UUID = None
        self.issuer_type: IdType = None
        self.audience: list[str] = [f'urn:network-{network_name}']
        self.secret: Secret = None
        self.service_id: int = None

        self.encoded: str = None
        self.decoded: dict[str:str] = None
        self.verified = None

    @staticmethod
    def create(identifier: UUID, id_type: IdType, secret: Secret,
               network_name: str, service_id: int = None,
               expiration_days: int = JWT_EXPIRATION_DAYS) -> str:
        '''
        Creates an authorization token

        :params
        :raises: ValueError
        '''

        _LOGGER.debug('Creating a JWT')
        jwt = JWT(network_name)

        if id_type == IdType.ACCOUNT:
            jwt.issuer = f'urn:account_id-{identifier}'
        elif id_type == IdType.MEMBER:
            jwt.issuer = f'urn:member_id-{identifier}'
        else:
            raise ValueError(
                'JWTs are only for created for accounts and members'
            )

        jwt.service_id = service_id

        jwt.secret = secret

        jwt.expiration = (
            datetime.now(tz=timezone.utc) + timedelta(days=expiration_days)
        )
        jwt.encode()

        return jwt

    def encode(self) -> str:
        data = {
            'exp': self.expiration,
            'iss': self.issuer,
            'aud': self.audience,
        }
        if self.service_id is not None:
            data['service_id'] = self.service_id

        jwt = py_jwt.encode(
            data, self.secret.private_key, algorithm=JWT_ALGO_PREFFERED
        )
        self.verified = True

        self.encoded = jwt

        return self.encoded

    @staticmethod
    def decode(authorization: str, secret: Secret, network: str):
        '''
        Decode an encoded JWT with or without verification.

        :param authorization: the encoded JWT
        :param secret: verification will not be performed if None is specified
        :param audience: the audience members that must be in the JWT
        :returns: JWT
        '''

        if authorization.startswith('bearer'):
            authorization = authorization[len('bearer'):]

        authorization = authorization.strip()

        audience = [f'urn:network-{network}']
        if secret:
            data = py_jwt.decode(
                authorization, secret.cert.public_key(), leeway=10,
                audience=audience, algorithms=JWT_ALGO_ACCEPTED
            )
        else:
            # Decode without verification of the signature
            data = py_jwt.decode(
                authorization, leeway=10, audience=audience,
                algorithms=JWT_ALGO_ACCEPTED,
                options={'verify_signature': False}
            )

        jwt = JWT(data['aud'])
        jwt.expiration = data['exp']
        jwt.issuer = data.get('iss')
        if not jwt.issuer:
            raise ValueError('No issuer specified in the JWT token')

        if jwt.issuer.startswith('urn'):
            jwt.issuer = jwt.issuer[4:]

        if jwt.issuer.startswith('member_id-'):
            jwt.issuer_type = IdType.MEMBER
            jwt.issuer_id = UUID(jwt.issuer[len('member_id-'):])
        elif jwt.issuer.startswith('account_id-'):
            jwt.issuer_type = IdType.ACCOUNT
            jwt.issuer_id = UUID(jwt.issuer[len('account_id-'):])
        else:
            raise ValueError(f'Invalid issuer in JWT: {jwt.issuer}')

        jwt.audience = data['aud']

        jwt.service_id = data.get('service_id')
        if jwt.service_id is not None:
            jwt.service_id = int(jwt.service_id)

        jwt.secret = secret
        if jwt.secret:
            jwt.verified = True

        return jwt

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

        if isinstance(config.server, ServiceServer):
            # Let's see if we have the public cert of the issuer of the JWT

            if self.service_id is None:
                raise ValueError('No service ID specified in the JWT')

            if self.issuer_type == IdType.ACCOUNT:
                raise ValueError(
                    'Service API can not be called with a JWT for an account'
                )

            secret: MemberSecret = MemberSecret(
                self.issuer_id, self.service_id, None,
                config.server.service.network
            )
        elif (isinstance(config.server, PodServer)
                and self.service_id is not None):
            # We have a JWT signed by a member of a service and we are
            # running on a pod, let's get the secret for the membership
            await config.server.account.load_memberships()
            member = config.server.account.memberships.get(self.service_id)
            if member:
                if member.member_id != self.issuer_id:
                    raise NotImplementedError(
                        'We do not yet support JWTs signed by other members'
                    )

                secret = member.tls_secret
            else:
                # We don't want to give details in the error message as it
                # could allow people to discover which services a pod has
                # joined
                _LOGGER.exception(
                    f'Unknown service ID: {self.service_id}'
                )
                raise ValueError
        elif isinstance(config.server, PodServer) and self.service_id is None:
            # We are running on the pod and the JWT is signed by the account
            secret = config.server.account.tls_secret
        else:
            _LOGGER.exception(
                f'Could not get the secret for {self.id_type.value}{self.id}'
            )
            raise ValueError

        return secret
