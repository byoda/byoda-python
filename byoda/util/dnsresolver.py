'''
DnsResolver class

provides basic functionality to lookup A records

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from logging import Logger
from logging import getLogger
from datetime import datetime
from datetime import timezone

from ipaddress import IPv4Address, IPv6Address, ip_address as IpAddress

import dns.resolver

_LOGGER: Logger = getLogger(__name__)

DNS_DIRSERVER_ADDRESSES: list[str] = []
DNS_DIRSERVER_EXPIRES: datetime = datetime.now(tz=timezone.utc)


class DnsResolver:
    def __init__(self, network: str) -> None:
        _LOGGER.debug('Initializing DNS resolver')
        # HACK: avoid test cases from needing their own DNS server
        if network in ('byodafunctest.net'):
            self.network = 'byoda.net'
        else:
            self.network: str = network

        self.resolver = dns.resolver.Resolver()
        self.resolver.timeout = 1
        self.resolver.lifetime = 1

        if (not DNS_DIRSERVER_ADDRESSES
                or DNS_DIRSERVER_EXPIRES < datetime.now(tz=timezone.utc)):
            self._update_dirserver_ips()

        _LOGGER.debug('Initialized DNS resolver')

    def _update_dirserver_ips(self) -> None:
        _LOGGER.debug('Updating directory server IP addresses')

        self.resolver.nameservers = ['1.1.1.1', '8.8.8.8']
        ips: list[str] = self.resolve(
            f'dir.{self.network}', force=True
        )
        ips_as_str: list[str] = [str(ip) for ip in ips]

        global DNS_DIRSERVER_ADDRESSES
        DNS_DIRSERVER_ADDRESSES = ips_as_str

        self.resolver.nameservers = DNS_DIRSERVER_ADDRESSES
        _LOGGER.debug(
            f'Setting nameserver(s) to use to: {DNS_DIRSERVER_ADDRESSES}'
        )
        global DNS_DIRSERVER_EXPIRES
        DNS_DIRSERVER_EXPIRES = datetime.now(tz=timezone.utc)
        _LOGGER.debug('Updated directory server IP addresses')

    def resolve(self, fqdn: str, force: bool = False) -> list[IpAddress]:
        '''
        Looks up the DNS A records for the provided FQDN
        '''

        _LOGGER.debug(f'Resolving FQDN: {fqdn}')

        if not force and DNS_DIRSERVER_EXPIRES < datetime.now(tz=timezone.utc):
            self._update_dirserver_ips()

        ips: list = []
        try:
            answer: dns.resolver.Answer = self.resolver.resolve(fqdn)
            for rr in answer.rrset.items:
                try:
                    ip: IPv4Address | IPv6Address = IpAddress(rr.address)
                    ips.append(ip)
                except ValueError:
                    pass
        except (dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            pass

        _LOGGER.debug(
            f'FQDN addresses {fqdn}: {", ".join([str(ip) for ip in ips])}'
        )

        return ips
