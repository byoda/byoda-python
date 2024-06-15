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
        self.is_funded: bool = False
        self.issuer: str = LiteJWT.get_issuer()
        self.audience: list[str] = [self.issuer]

        self.secrets: list[str] = secrets
        if isinstance(self.secrets, str):
            self.secrets = [self.secrets]
        if isinstance(self.secrets, tuple):
            self.secrets = list(self.secrets)

        if not (self.secrets or config.jwt_secrets):
            raise ValueError('No JWT secrets have been defined')

        self.secrets.extend(config.jwt_secrets)

        LiteJWT.setup_metrics()

    @staticmethod
    def get_issuer() -> str:
        '''
        Get the issuer
        '''

        return \
            f'urn:network-{config.DEFAULT_NETWORK}:service-{config.SERVICE_ID}'

    @staticmethod
    def create_auth_token(lite_id: UUID, is_funded: bool,
                          secrets: list[str] = []) -> str:
        '''
        Create an access token

        :param data: The data to be included in the token
        '''

        metrics: dict[str, Counter] = config.metrics

        expiration: datetime = \
            datetime.now(tz=UTC) + timedelta(days=JWT_EXPIRATION_DAYS)

        jwt = LiteJWT(secrets=secrets)
        access_token: str = py_jwt.encode(
            {
                'lite_id': str(lite_id),
                'is_funded': is_funded,
                'exp': expiration,
                'iss': jwt.issuer,
                'aud': jwt.audience,
                'iat': datetime.now(tz=UTC),
            },
            jwt.secrets[0],
            algorithm=JWT_ALGO_PREFFERED,
        )

        _LOGGER.debug(
            f'Created access token for Lite Account ID {lite_id}'
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

        metric = 'jwt_token_invalid_algorithm'
        metrics[metric] = Counter(
            metric, 'Number of JWT tokens that have an invalid algorithm'
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
