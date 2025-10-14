'''
API models for IP Addresses

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from logging import Logger
from logging import getLogger
from ipaddress import IPv4Address
from ipaddress import IPv6Address

from pydantic import BaseModel

_LOGGER: Logger = getLogger(__name__)


class IpAddressResponseModel(BaseModel):
    ipv4_address: IPv4Address | None = None
    ipv6_address: IPv6Address | None = None

    def __repr__(self) -> str:
        return (
            '<IpAddressResponseModel={IPv4Address: str, IPv6Address: str}>'
        )

    def as_dict(self) -> dict[str, str]:
        return {
            'ipv4_address': self.ipv4_address.exploded,
            'ipv6_address': self.ipv6_address.exploded
        }
