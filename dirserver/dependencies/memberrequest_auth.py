'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from typing import Optional

from fastapi import Header, HTTPException, Request

from byoda import config

from byoda.requestauth.requestauth import RequestAuth, TlsStatus
from byoda.exceptions import NoAuthInfo

from byoda.util.secrets import MembersCaSecret
from byoda.util.secrets import ServiceCaSecret

_LOGGER = logging.getLogger(__name__)


class MemberRequestAuth(RequestAuth):
    def __init__(self,
                 request: Request, service_id: int,
                 x_client_ssl_verify: Optional[TlsStatus] = Header(None),
                 x_client_ssl_subject: Optional[str] = Header(None),
                 x_client_ssl_issuing_ca: Optional[str] = Header(None)):
        '''
        Get the authentication info for the client that made the API call.
        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

        :param service_id: the service identifier for the service
        :returns: (n/a)
        :raises: HTTPException
        '''

        if service_id is None or isinstance(service_id, int):
            pass
        elif isinstance(service_id, str):
            service_id = int(service_id)
        else:
            raise ValueError(
                f'service_id must be an integer, not {type(service_id)}'
            )

        try:
            super().__init__(
                x_client_ssl_verify or TlsStatus.NONE, x_client_ssl_subject,
                x_client_ssl_issuing_ca, request.client.host
            )
        except NoAuthInfo:
            raise HTTPException(
                status_code=401, detail='Authentication failed'
            )

        if self.client_cn is None and self.issuing_ca_cn is None:
            raise HTTPException(
                status_code=401, detail='Authentication failed'
            )

        network = config.network

        # We verify the cert chain by creating dummy secrets for each
        # applicable CA and then review if that CA would have signed
        # the commonname found in the certchain presented by the
        # client
        try:
            # Member cert gets signed by Service Member CA
            member_ca_secret = MembersCaSecret(
                service_id, network=network.network
            )
            entity_id = member_ca_secret.review_commonname(self.client_cn)
            self.member_id = entity_id.uuid
            self.service_id = entity_id.service_id

            # The Member CA cert gets signed by the Service CA
            service_ca_secret = ServiceCaSecret(
                service_id, network=network.network
            )
            service_ca_secret.review_commonname(self.issuing_ca_cn)
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail=(
                    f'Inccorrect c_cn {self.client_cn} issued by '
                    f'{self.issuing_ca_cn} for service {service_id} on '
                    f'network {network.network}'
                )
            ) from exc

        self.is_authenticated = True
