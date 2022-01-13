'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import Optional
from ipaddress import ip_address as IpAddress

from byoda.config import server

from fastapi import Header, HTTPException

from byoda.datatypes import HttpRequestMethod

from byoda.requestauth.requestauth import RequestAuth, TlsStatus
from byoda.exceptions import MissingAuthInfo

_LOGGER = logging.getLogger(__name__)


class ServiceRequestAuth(RequestAuth):
    def __init__(self, tls_status: TlsStatus,
                 client_dn: str, issuing_ca_dn: str,
                 remote_addr: IpAddress, method: HttpRequestMethod):
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

        if isinstance(service_id, int):
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
        except MissingAuthInfo:
            raise HTTPException(
                status_code=401, detail='Authentication failed'
            )

        if self.client_cn is None and self.issuing_ca_cn is None:
            raise HTTPException(
                status_code=401, detail='Authentication failed'
            )

        # We verify the cert chain by creating dummy secrets for each
        # applicable CA and then review if that CA would have signed
        # the commonname found in the certchain presented by the
        # client.
        self.check_service_cert(service_id, server.network)

        self.is_authenticated = True
