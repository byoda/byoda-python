'''
API models for IP Addresses

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from ipaddress import IPv4Address, IPv6Address
from pydantic import BaseModel

_LOGGER = logging.getLogger(__name__)


class IpAddressResponseModel(BaseModel):
    ipv4_address: IPv4Address = None
    ipv6_address: IPv6Address = None

    def __repr__(self):
        return(
            '<IpAddressResponseModel={IPv4Address: str, IPv6Address: str}>'
        )

    def as_dict(self):
        return {
            'ipv4_address': self.ipv4_address.exploded,
            'ipv6_address': self.ipv6_address.exploded
        }
