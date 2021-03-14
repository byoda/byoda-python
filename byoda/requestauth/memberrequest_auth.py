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

from byoda.util.secrets import MembersCaSecret
from byoda.util.secrets import ServiceCaSecret

_LOGGER = logging.getLogger(__name__)


class MemberRequestAuth(RequestAuth):
    def __init__(self, service_id: int, required: bool = True):
        '''
        Get the authentication info for the client that made the API call.
        The reverse proxy has already validated that the client calling the
        API is the owner of the private key for the certificate it presented
        so we trust the HTTP headers set by the reverse proxy

        service_id
        ;param required: should AuthFailure exception be thrown if
        authentication fails
        :returns: (n/a)
        :raises: ValueError if the no authentication is available and the
        parameter 'required' has a value of True. ValueError if authentication
        was provided but is incorrect, regardless of the value of the
        'required' parameter
        '''

        if service_id is None or isinstance(service_id, int):
            pass
        elif isinstance(service_id, str):
            service_id = int(service_id)
        else:
            raise ValueError(
                f'service_id must be an integer, not {type(service_id)}'
            )

        super().__init__(required=required)

        if self.client_cn is None and self.issuing_ca_cn is None:
            if required:
                raise AuthFailure('No commonname available for authentication')
            else:
                return
        network = config.network

        # We verify the cert chain by creating dummy secrets for each
        # applicable CA and then review if that CA would have signed
        # the commonname found in the certchain presented by the
        # client
        try:
            # Member cert gets signed by Service Member CA
            member_ca_secret = MembersCaSecret(
                service_id, network=network.network
            )
            entity_id = member_ca_secret.review_commonname(self.client_cn)
            self.member_id = entity_id.uuid
            self.service_id = entity_id.service_id

            # The Member CA cert gets signed by the Service CA
            service_ca_secret = ServiceCaSecret(
                service_id, network=network.network
            )
            service_ca_secret.review_commonname(self.issuing_ca_cn)
        except ValueError as exc:
            raise AuthFailure(
                f'Inccorrect c_cn {self.client_cn} issued by '
                f'{self.issuing_ca_cn} for service {service_id} on '
                f'network {network.network}'
            ) from exc

        self.is_authenticated = True
