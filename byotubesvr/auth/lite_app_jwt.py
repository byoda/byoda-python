'''
Wrapper class for the PyJWT module

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license
'''

from uuid import UUID
from logging import getLogger
from datetime import UTC
from datetime import datetime
from datetime import timedelta

import jwt as py_jwt

from cryptography import x509

from prometheus_client import Counter

from .lite_jwt import LiteJWT

from byoda.limits import MAX_APP_TOKEN_EXPIRATION

from byoda.util.logger import Logger

from byoda import config

_LOGGER: Logger = getLogger(__name__)

JWT_EXPIRATION_DAYS = 365
JWT_ALGO_PREFFERED = 'RS256'
JWT_ALGO_ACCEPTED: list[str] = ['RS256']


class LiteAppJWT(LiteJWT):
    '''
    Wrapper class for the PyJWT module
    '''

    def __init__(self, app_id: UUID, secrets: list[x509.Certificate] = [],
                 ) -> None:
        '''
        Constructor
        '''

        self.expiration: datetime = None

        self.app_id: UUID = app_id

        self.issuer: str = LiteJWT.get_issuer()

        self.audience: list[str] = [f'{self.issuer}:app-{app_id}']

        self.secrets: list[x509.Certificate] = secrets
        if isinstance(self.secrets, x509.Certificate):
            self.secrets = [self.secrets]
        if isinstance(self.secrets, tuple):
            self.secrets = list(self.secrets)

        if not (secrets or config.jwt_asym_secrets):
            raise ValueError('No JWT secrets have been defined')

        self.secrets.extend(config.jwt_asym_secrets)

        LiteJWT.setup_metrics()

    @staticmethod
    def create_auth_token(lite_id: UUID, app_id: UUID,
                          secrets: list[x509.Certificate] = []) -> str:
        '''
        Create an JWT token to be used with 3rd-party app servers

        :param data: The data to be included in the token
        '''

        metrics: dict[str, Counter] = config.metrics

        expiration: datetime = \
            datetime.now(tz=UTC) + timedelta(seconds=MAX_APP_TOKEN_EXPIRATION)

        jwt = LiteAppJWT(app_id=app_id, secrets=secrets)
        access_token: str = py_jwt.encode(
            {
                'lite_id': str(lite_id),
                'service_id': config.SERVICE_ID,
                'exp': expiration,
                'iss': jwt.issuer,
                'aud': jwt.audience,
                'iat': datetime.now(tz=UTC),
            },
            jwt.secrets[0][1],
            algorithm=JWT_ALGO_PREFFERED,
        )

        _LOGGER.debug(
            f'Created access token for Lite Account ID {lite_id}: '
            f'{access_token} for app {app_id if app_id else "N/A"}'
        )

        metrics['jwt_token_created'].inc()

        return access_token

    @staticmethod
    def verify_auth_token(token: str, secrets: list[str] = []) -> UUID | None:
        '''
        Decode an access token

        :param token: The token to be decoded
        :returns: UUID of the Lite Account ID or None if validation fails
        '''

        metrics: dict[str, Counter] = config.metrics

        _LOGGER.debug(f'Decode access token: {token}')

        jwt = LiteJWT(secrets=secrets)

        for secret in jwt.secrets:
            try:
                decoded_token: dict[str, any] = py_jwt.decode(
                    token, secret, algorithms=JWT_ALGO_ACCEPTED,
                    audience=jwt.audience, issuer=jwt.issuer,
                    options={'require': ['exp', 'iss', 'aud', 'iat', 'lite_id']}
                )
                return UUID(decoded_token['lite_id'])
            except py_jwt.ExpiredSignatureError:
                metrics['jwt_token_expired'].inc()
            except py_jwt.InvalidSignatureError:
                metrics['jwt_token_invalid_signature'].inc()
            except py_jwt.ImmatureSignatureError:
                metrics['jwt_token_immature_signature'].inc()
            except py_jwt.InvalidAudienceError:
                metrics['jwt_token_invalid_audience'].inc()
            except py_jwt.InvalidIssuerError:
                metrics['jwt_token_invalid_issuer'].inc()
            except py_jwt.InvalidKeyError:
                metrics['jwt_token_invalid_key'].inc()
            except py_jwt.InvalidAlgorithmError:
                metrics['jwt_token_invalid_algorithm'].inc()
            except py_jwt.MissingRequiredClaimError:
                metrics['jwt_token_missing_required_claim'].inc()
            except py_jwt.DecodeError:
                # We may have used an older secret so this is not an error
                pass
            except py_jwt.InvalidTokenError:
                metrics['jwt_token_invalid'].inc()
            except Exception as exc:
                _LOGGER.debug(f'Failed to decode token: {token}: {exc}')

        metrics['jwt_token_decode_failures'].inc()

        return None
