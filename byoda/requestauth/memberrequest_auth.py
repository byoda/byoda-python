'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from typing import Optional
from ipaddress import ip_address as IpAddress

from fastapi import Header, HTTPException, Request

from byoda.config import server

from byoda.datatypes import HttpRequestMethod

from byoda.requestauth.requestauth import RequestAuth, TlsStatus
from byoda.exceptions import NoAuthInfo

_LOGGER = logging.getLogger(__name__)

class MemberRequestAuth_Fast(MemberRequesTauth):
    '''
    Wrapper for FastApi dependency
    '''

    def __init__(self, request: Request,
                 x_client_ssl_verify: Optional[TlsStatus] = Header(None),
                 x_client_ssl_subject: Optional[str] = Header(None),
                 x_client_ssl_issuing_ca: Optional[str] = Header(None)):
        super().__init__(
            x_client_ssl_verify or TlsStatus.NONE, x_client_ssl_subject,
            x_client_ssl_issuing_ca, request.client.host
        )


class MemberRequestAuth(RequestAuth):
    def __init__(self, service_id: int, tls_status: TlsStatus,
                 client_dn: str, issuing_ca_dn: str,
                 remote_addr: IpAddress, method: HttpRequestMethod):
        '''
        Get the authentication info for the client that made the API call.
        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

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
            super().__init__(tls_status, client_dn, issuing_ca_dn, remote_addr)
        except NoAuthInfo:
            raise HTTPException(
                status_code=401, detail='Authentication failed'
            )

        if self.client_cn is None and self.issuing_ca_cn is None:
            raise HTTPException(
                status_code=401, detail='Authentication failed'
            )

        self.check_member_cert(service_id, server.network)

        self.is_authenticated = True
