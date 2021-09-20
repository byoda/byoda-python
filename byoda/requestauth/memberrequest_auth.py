'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from typing import Optional
from ipaddress import ip_address as IpAddress

from fastapi import Header, HTTPException, Request

from byoda import config

from byoda.datatypes import HttpRequestMethod

from byoda.requestauth.requestauth import RequestAuth, TlsStatus
from byoda.exceptions import MissingAuthInfo

_LOGGER = logging.getLogger(__name__)


class MemberRequestAuth_Fast(RequestAuth):
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
    def __init__(self, tls_status: TlsStatus,
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

        server = config.server

        service_id = MemberRequestAuth.get_service_id(client_dn)

        try:
            super().__init__(tls_status, client_dn, issuing_ca_dn, remote_addr)
        except MissingAuthInfo:
            raise HTTPException(
                status_code=401, detail='Authentication failed'
            )

        if self.client_cn is None and self.issuing_ca_cn is None:
            raise HTTPException(
                status_code=401, detail='Authentication failed'
            )

        self.check_member_cert(service_id, server.network)

        self.is_authenticated = True

    @staticmethod
    def get_service_id(commonname: str) -> str:
        '''
        Extracts the service_id from the IdType from a common name
        in a x.509 certificate for Memberships

        :param commonname: x509 common name
        :returns: service_id
        :raises: ValueError if the service_id could not be extracted
        '''

        commonname_bits = commonname.split('.')
        if len(commonname_bits) < 4:
            raise HTTPException(
                status_code=400,
                detail=f'Invalid common name {commonname}'
            )

        subdomain = commonname_bits[1]
        if '-' in subdomain:
            # For members, subdomain has format 'members-<service-id>'
            service_id = int(subdomain[subdomain.find('-')+1:])
            return service_id

        raise HTTPException(
            status_code=403,
            detail=f'Invalid format for common name: {commonname}'
        )
