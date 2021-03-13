'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from byoda import config

from .request_auth import RequestAuth, AuthFailure

from byoda.util.secrets import NetworkAccountsCaSecret
from byoda.util.secrets import NetworkRootCaSecret

_LOGGER = logging.getLogger(__name__)


class AccountRequestAuth(RequestAuth):
    def __init__(self, required: bool = True):
        '''
        Get the authentication info for the client that made the API call.
        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

        ;param required: should AuthFailure exception be thrown if
        authentication fails
        :returns: (n/a)
        :raises: ValueError if the no authentication is available and the
        parameter 'required' has a value of True. ValueError if authentication
        was provided but is incorrect, regardless of the value of the
        'required' parameter
        '''
        super().__init__(required)

        network = config.network

        if self.client_cn is None and self.issuing_ca_cn is None:
            if required:
                raise AuthFailure('No commonname available for authentication')
            else:
                return

        # We verify the cert chain by creating dummy secrets for each
        # applicable CA and then review if that CA would have signed
        # the commonname found in the certchain presented by the
        # client
        try:
            # Account certs get signed by the Network Accounts CA
            accounts_ca_secret = NetworkAccountsCaSecret(
                network=network.network
            )
            accounts_ca_secret.review_commonname(self.client_cn)

            # Network Accounts CA cert gets signed by root CA of the
            # network
            root_ca_secret = NetworkRootCaSecret(network=network.network)
            root_ca_secret.review_commonname(self.issuing_ca_cn)
        except ValueError as exc:
            raise AuthFailure(
                f'Inccorrect c_cn {self.client_cn} issued by '
                f'{self.issuing_ca_cn} on network '
                f'{network.network}'
            ) from exc

        self.is_authenticated = True
