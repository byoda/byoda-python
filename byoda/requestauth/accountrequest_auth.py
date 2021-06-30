'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from ipaddress import ip_address as IpAddress

from fastapi import HTTPException

from byoda import config

from byoda.datatypes import HttpRequestMethod

from byoda.requestauth.requestauth import RequestAuth, TlsStatus
from byoda.exceptions import NoAuthInfo

_LOGGER = logging.getLogger(__name__)


class AccountRequestAuth(RequestAuth):
    def __init__(self, tls_status: TlsStatus,
                 client_dn: str, issuing_ca_dn: str,
                 remote_addr: IpAddress, method: HttpRequestMethod):
        '''
        Get the authentication info for the client that made the API call.
        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

        :returns: (n/a)
        :raises: HTTPException
        '''
        try:
            super().__init__(
                tls_status, client_dn, issuing_ca_dn, remote_addr
            )
        except NoAuthInfo:
            # Authentication for GET/POST /api/v1/network/account is optional
            if method in (HttpRequestMethod.GET, HttpRequestMethod.POST):
                return
            else:
                raise HTTPException(
                    status_code=403, detail='No authentication provided'
                )

        self.check_account_cert(config.network)

        self.is_authenticated = True
