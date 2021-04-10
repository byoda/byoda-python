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

from byoda.util.secrets import NetworkAccountsCaSecret
from byoda.util.secrets import NetworkRootCaSecret

_LOGGER = logging.getLogger(__name__)


class AccountRequestAuth(RequestAuth):
    def __init__(self,
                 request: Request,
                 x_client_ssl_verify: Optional[TlsStatus] = Header(None),
                 x_client_ssl_subject: Optional[str] = Header(None),
                 x_client_ssl_issuing_ca: Optional[str] = Header(None)):
        '''
        Get the authentication info for the client that made the API call.
        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

        :param request: Starlette request instance
        :param service_id: the service identifier for the service
        :returns: (n/a)
        :raises: HTTPException
        '''
        try:
            super().__init__(
                x_client_ssl_verify or TlsStatus.NONE, x_client_ssl_subject,
                x_client_ssl_issuing_ca, request.client.host
            )
        except NoAuthInfo:
            # Authentication for GET /api/v1/network/account is optional
            if request.method in ('GET', 'POST'):
                return
            else:
                raise HTTPException(
                    status_code=403, detail='No authentication provided'
                )

        network = config.network

        # We verify the cert chain by creating dummy secrets for each
        # applicable CA and then review if that CA would have signed
        # the commonname found in the certchain presented by the
        # client
        try:
            # Account certs get signed by the Network Accounts CA
            accounts_ca_secret = NetworkAccountsCaSecret(
                network=network.network
            )
            entity_id = accounts_ca_secret.review_commonname(self.client_cn)
            self.account_id = entity_id.uuid

            # Network Accounts CA cert gets signed by root CA of the
            # network
            root_ca_secret = NetworkRootCaSecret(network=network.network)
            root_ca_secret.review_commonname(self.issuing_ca_cn)
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail=(
                    f'Inccorrect c_cn {self.client_cn} issued by '
                    f'{self.issuing_ca_cn} on network '
                    f'{network.network}'
                )
            ) from exc

        self.is_authenticated = True
