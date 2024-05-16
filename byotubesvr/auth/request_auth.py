'''
Helper functions for Lite API request authentication

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license
'''

from uuid import UUID
from logging import Logger
from logging import getLogger

from fastapi import Request
from fastapi import HTTPException

from byotubesvr.auth.lite_jwt import LiteJWT

_LOGGER: Logger = getLogger(__name__)


class LiteRequestAuth:
    '''
    Helper functions for Lite API request authentication
    '''

    def __init__(self, request: Request) -> None:
        auth_header: str | None = request.headers.get('Authorization')

        if not auth_header:
            raise HTTPException(
                401, 'This API requires an Authorization header'
            )

        auth_parts: list[str] = auth_header.split(' ')
        if not auth_parts or len(auth_parts) < 1:
            raise HTTPException(
                401, 'Invalid format for Authorization header'
            )

        token: str = auth_parts[-1]

        self.lite_id: UUID | None = LiteJWT.verify_auth_token(token)

        if not self.lite_id:
            raise HTTPException(401, 'Invalid token')

    @staticmethod
    def setup_metrics() -> None:
        '''
        Setup the metrics for RequestAuth class
        '''

        #metrics: dict[str, Counter] = config.metrics
        #TODO: Add metrics using opentelemetry
