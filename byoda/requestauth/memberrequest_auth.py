'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging

from fastapi import Header, HTTPException, Request

from byoda import config

from byoda.requestauth.requestauth import RequestAuth, TlsStatus
from byoda.exceptions import ByodaMissingAuthInfo

_LOGGER = logging.getLogger(__name__)


# TODO: remove, obsolete code?
class MemberRequestAuth_Fast(RequestAuth):
    '''
    Wrapper for FastApi dependency
    '''

    def __init__(self, request: Request,
                 x_client_ssl_verify: TlsStatus | None = Header(None),
                 x_client_ssl_subject: str | None = Header(None),
                 x_client_ssl_issuing_ca: str | None = Header(None)):
        super().__init__(
            x_client_ssl_verify or TlsStatus.NONE, x_client_ssl_subject,
            x_client_ssl_issuing_ca, request.client.host
        )


class MemberRequestAuth(RequestAuth):
    async def authenticate(self, tls_status: TlsStatus,
                           client_dn: str, issuing_ca_dn: str,
                           client_cert: str, authorization: str):
        '''
        Get the authentication info for the client that made the API call.
        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

        :param service_id: the service identifier for the service
        :returns: whether the client successfully authenticated
        :raises: HTTPException
        '''

        server = config.server

        try:
            await super().authenticate(
                tls_status, client_dn, issuing_ca_dn,
                client_cert, authorization
            )
        except ByodaMissingAuthInfo:
            raise HTTPException(
                status_code=401, detail='Authentication failed'
            )

        if (self.client_cn is None and authorization is None):
            raise HTTPException(
                status_code=401, detail='Authentication failed'
            )

        if client_dn:
            self.check_member_cert(self.service_id, server.network)

        self.is_authenticated = True

        return self.is_authenticated

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
            status_code=400,
            detail=f'Invalid format for common name: {commonname}'
        )
