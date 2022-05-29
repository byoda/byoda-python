'''
Wrapper class for the PyJWT module

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import logging
from uuid import UUID
from typing import TypeVar
from datetime import datetime, timezone, timedelta

import jwt as py_jwt


from byoda.secrets import Secret

from byoda.datatypes import IdType

from byoda import config

_LOGGER = logging.getLogger(__name__)

ServiceServer = TypeVar('ServiceServer')
PodServer = TypeVar('PodServer')

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
    async def decode(authorization: str, secret: Secret, network: str,
                     download_remote_cert: bool = True):
        '''
        Decode an encoded JWT with or without verification.

        :param authorization: the encoded JWT
        :param secret: verification will not be performed if None is specified
        :param audience: the audience members that must be in the JWT
        :param download_remote_cert: should remote cert be downloaded to verify
        the signature of the JWT? The value for this parameter is ignored when
        a value for the 'secret' parameter is provided
        :raises: ValueError, FileNotFound
        :returns: JWT
        '''

        if authorization.startswith('bearer'):
            authorization = authorization[len('bearer'):]

        authorization = authorization.strip()

        # the py_jwt.decode function verifies the audience of the JWT
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

        if secret:
            jwt.verified = True
        else:
            jwt.verified = False

        jwt.expiration = data['exp']
        jwt.issuer = data.get('iss')
        if not jwt.issuer:
            raise ValueError('No issuer specified in the JWT')

        if jwt.issuer.startswith('urn:'):
            jwt.issuer = jwt.issuer[4:]
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

        jwt.service_id = data.get('service_id')
        if jwt.service_id is not None:
            jwt.service_id = int(jwt.service_id)

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
