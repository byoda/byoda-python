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

from prometheus_client import Counter

from byoda.util.logger import Logger

from byoda import config

_LOGGER: Logger = getLogger(__name__)

JWT_EXPIRATION_DAYS = 365
JWT_ALGO_PREFFERED = 'HS256'
JWT_ALGO_ACCEPTED: list[str] = ['HS256']


class LiteJWT:
    '''
    Wrapper class for the PyJWT module
    '''

    def __init__(self, secrets: list[str] = []) -> None:
        '''
        Constructor
        '''
        self.expiration: datetime = None
        self.issuer: str = None

        self.issuer: str = 'urn:BYOTube'
        self.audience: list[str] = ['urn:BYOTube']

        self.secrets: list[str] = secrets
        if not config.jwt_secrets:
            raise ValueError('No JWT secrets have been defined')

        self.secrets.extend(config.jwt_secrets)

        LiteJWT.setup_metrics()

    def create_auth_token(self, lite_id: UUID) -> str:
        '''
        Create an access token

        :param data: The data to be included in the token
        '''

        metrics: dict[str, Counter] = config.metrics

        expiration: datetime = \
            datetime.now(tz=UTC) + timedelta(days=JWT_EXPIRATION_DAYS)

        access_token: str = py_jwt.encode(
            {
                'lite_id': str(lite_id),
                'exp': expiration,
                'iss': self.issuer,
                'aud': self.audience,
                'iat': datetime.now(tz=UTC),
            },
            self.secrets[0],
            algorithm=JWT_ALGO_PREFFERED,
        )

        _LOGGER.debug(
            f'Created access token for Lite Account ID {lite_id}: '
            f'{access_token}'
        )

        metrics['jwt_token_created'].inc()
        return access_token

    def verify_access_token(self, token: str) -> UUID | None:
        '''
        Decode an access token

        :param token: The token to be decoded
        :returns: UUID of the Lite Account ID or None if validation fails
        '''

        metrics: dict[str, Counter] = config.metrics

        _LOGGER.debug(f'Decode access token: {token}')

        for secret in self.secrets:
            try:
                decoded_token = py_jwt.decode(
                    token, secret, algorithms=JWT_ALGO_ACCEPTED,
                    audience=self.audience, issuer=self.issuer,
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

    @staticmethod
    def setup_metrics() -> None:
        '''
        Setup metrics for the JWT module
        '''

        metrics: dict[str, any] = config.metrics

        metric: str = 'jwt_token_created'
        if metric in metrics:
            # Metrics have already been setup
            return

        metrics[metric] = Counter(metric, 'Number of JWT tokens created')

        metric = 'jwt_token_expired'
        metrics[metric] = Counter(
            metric, 'Number of JWT tokens that are expired'
        )

        metric = 'jwt_token_invalid_signature'
        metrics[metric] = Counter(
            metric, 'Number of JWT tokens that have an invalid signature'
        )

        metric = 'jwt_token_immature_signature'
        metrics[metric] = Counter(
            metric, 'Number of JWT tokens that have an immature signature'
        )

        metric = 'jwt_token_invalid_audience'
        metrics[metric] = Counter(
            metric, 'Number of JWT tokens that have an invalid audience'
        )

        metric = 'jwt_token_invalid_issuer'
        metrics[metric] = Counter(
            metric, 'Number of JWT tokens that have an invalid issuer'
        )

        metric = 'jwt_token_invalid_key'
        metrics[metric] = Counter(
            metric, 'Number of JWT tokens that have an invalid key'
        )

        metric = 'jwt_token_invalid_algorith'
        metrics[metric] = Counter(
            metric, 'Number of JWT tokens that have an invalid algorithm'
        )

        metric = 'jwt_token_invalid'
        metrics[metric] = Counter(
            metric, 'Number of JWT tokens that are invalid'
        )

        metric = 'jwt_token_missing_required_claim'
        metrics[metric] = Counter(
            metric, 'Number of JWT tokens that have a missing required claim'
        )

        metric = 'jwt_token_decode_failures'
        metrics[metric] = Counter(
            metric, 'Number of JWT tokens that failed to decrypt'
        )

