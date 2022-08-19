'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging

from fastapi import HTTPException

from byoda.requestauth.requestauth import RequestAuth, TlsStatus
from byoda.exceptions import ByodaMissingAuthInfo

from byoda import config

_LOGGER = logging.getLogger(__name__)


class ServiceRequestAuth(RequestAuth):
    async def authenticate(self, tls_status: TlsStatus,
                           client_dn: str, issuing_ca_dn: str,
                           authorization: str) -> bool:
        '''
        Get the authentication info for the client that made the API call.
        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

        :returns: (n/a)
        :raises: HTTPException
        '''

        server = config.server

        if authorization:
            _LOGGER.debug('Service called GraphQL API with a JWT')
            raise HTTPException(
                status_code=401,
                detail='Service must not call GraphQL APIs using JWTs'
            )

        try:
            _LOGGER.debug(
                f'Authenticating request by a service: {client_dn}'
            )
            await super().authenticate(
                tls_status, client_dn, issuing_ca_dn, authorization,
            )
        except ByodaMissingAuthInfo:
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
        self.check_service_cert(server.network)

        self.is_authenticated = True

    @staticmethod
    def get_service_id(commonname: str, authorization: str) -> str:
        '''
        Extracts the service_id from the IdType from a common name
        in a x.509 certificate for Memberships

        :param commonname: x509 common name
        :returns: service_id
        :raises: ValueError if the service_id could not be extracted
        '''

        if commonname:
            commonname_bits = commonname.split('.')
            if len(commonname_bits) < 4:
                raise HTTPException(
                    status_code=400,
                    detail=f'Invalid common name {commonname}'
                )

            subdomain = commonname_bits[1]
            if '-' in subdomain:
                # For services, subdomain has format 'service-<service-id>'
                service_id = int(subdomain[subdomain.find('-')+1:])
                return service_id

            raise HTTPException(
                status_code=403,
                detail=f'Invalid format for common name: {commonname}'
            )
        elif authorization:
            # TODO: get service_id from token
            raise NotImplementedError
        else:
            raise ByodaMissingAuthInfo('Missing common name')
