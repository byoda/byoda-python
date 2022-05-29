'''
Class PodServer derived from Server class for modelling
a server that hosts a BYODA Service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import TypeVar, Dict

from byoda.util.api_client import RestApiClient
from byoda.util.paths import Paths

from byoda.datatypes import ServerType
from byoda.datatypes import IdType

from byoda.secrets import AccountSecret
from byoda.secrets import MemberSecret

from byoda import config

from .server import Server


_LOGGER = logging.getLogger(__name__)


Network = TypeVar('Network')
RegistrationStatus = TypeVar('RegistrationStatus')
JWT = TypeVar('JWT')
Member = TypeVar('Member')
Account = TypeVar('Account')


class PodServer(Server):
    HTTP_PORT = 8000

    def __init__(self, network: Network = None):
        super().__init__(network)

        self.server_type = ServerType.POD
        self.service_summaries: Dict[int:Dict] = None
        self.account_unencrypted_private_key_file: str = None

    async def load_secrets(self, password: str = None):
        '''
        Loads the secrets used by the podserver
        '''
        await self.account.load_secrets()

        # We use the account secret as client TLS cert for outbound
        # requests and as private key for the TLS server
        filepath = await self.account.tls_secret.save_tmp_private_key()

        config.requests.cert = (
            self.account.tls_secret.cert_file, filepath
        )

    async def get_registered_services(self):
        '''
        Downloads a list of service summaries
        '''

        network = self.network

        url = network.paths.get(Paths.NETWORKSERVICES_API)
        resp = await RestApiClient.call(url)

        self.network.service_summaries = dict()
        if resp.status == 200:
            summaries = await resp.json()
            for summary in summaries.get('service_summaries', []):
                self.network.service_summaries[summary['service_id']] = summary
            _LOGGER.debug(
                f'Read summaries for {len(self.network.service_summaries)} '
                'services'
            )
        else:
            _LOGGER.debug(
                'Failed to retrieve list of services from the network: '
                f'HTTP {resp.status}'
            )

    async def review_jwt(self, jwt: JWT):
        '''
        Reviews the JWT for processing on a pod server

        :param jwt: the received JWT
        :raises: ValueError:
        :returns: (none)
        '''

        if jwt.service_id is None and jwt.issuer_type != IdType.ACCOUNT:
            raise ValueError(
                'Service ID must not specified in the JWT for an account'
            )

        account: Account = config.server.account
        if jwt.issuer_type == IdType.ACCOUNT:
            if jwt.issuer_id != account.account_id:
                raise ValueError(
                    f'Received JWT for wrong account_id: {jwt.issuer_id}'
                )

        elif jwt.issuer_type == IdType.MEMBER:
            await config.server.account.load_memberships()
            member: Member = config.server.account.memberships.get(
                jwt.service_id
            )

            if not member:
                # We don't want to give details in the error message as it
                # could allow people to discover which services a pod has
                # joined
                _LOGGER.exception(
                    f'Unknown service ID: {self.service_id}'
                )
                raise ValueError
        else:
            raise ValueError(
                f'Podserver does not support JWTs for {jwt.issuer_type}'
            )

    async def get_jwt_secret(self, jwt: JWT):
        '''
        Load the public key for the secret that was used to sign the jwt.
        '''

        if jwt.issuer_type == IdType.ACCOUNT:
            secret: AccountSecret = config.server.account.tls_secret
        elif jwt.issuer_type == IdType.MEMBER:
            await config.server.account.load_memberships()
            member: Member = config.server.account.memberships.get(
                jwt.service_id
            )

            if member.member_id == jwt.issuer_id:
                secret: MemberSecret = member.tls_secret
            else:
                # see if we can get the secret of the other memember so
                # we can verify the JWT signature wit hthat secret
                secret: MemberSecret = await member.download_secret(
                    jwt.issuer_id
                )

        return secret

    def accepts_jwts(self):
        return True
