'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from logging import getLogger
from byoda.util.logger import Logger

from fastapi import HTTPException

from byoda.datamodel.account import Account

from byoda.datatypes import IdType

from byoda.servers.pod_server import PodServer

from byoda import config

from byoda.requestauth.requestauth import RequestAuth
from byoda.requestauth.requestauth import TlsStatus

from byoda.exceptions import ByodaMissingAuthInfo

_LOGGER: Logger = getLogger(__name__)


class MemberRequestAuth(RequestAuth):
    async def authenticate(self, tls_status: TlsStatus,
                           client_dn: str, issuing_ca_dn: str,
                           client_cert: str, authorization: str):
        '''
        Get the authentication info for the client that made the API call.
        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

        :returns: whether the client successfully authenticated
        :raises: HTTPException
        '''

        server: PodServer = config.server
        account: Account = server.account

        try:
            jwt = await super().authenticate(
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
        else:
            member = await account.get_membership(jwt.service_id)
            jwt.check_scope(IdType.MEMBER, member.member_id)

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
