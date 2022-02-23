'''
DnsResolver class

provides basic functionality to lookup A records

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from datetime import datetime, timezone

from ipaddress import ip_address as IpAddress

import dns.resolver

_LOGGER = logging.getLogger(__name__)

DNS_DIRSERVER_ADDRESSES = []
DNS_DIRSERVER_EXPIRES = datetime.now(tz=timezone.utc)


class DnsResolver:
    def __init__(self, network: str):
        # HACK: avoid test cases from needing their own DNS server
        if network in ('byodafunctest.net'):
            self.network = 'byoda.net'
        else:
            self.network = network

        self.resolver = dns.resolver.Resolver()
        self.resolver.timeout = 1
        self.resolver.lifetime = 1

        if (not DNS_DIRSERVER_ADDRESSES
                or DNS_DIRSERVER_EXPIRES < datetime.now(tz=timezone.utc)):
            self._update_dirserver_ips()

    def _update_dirserver_ips(self):
        self.resolver.nameservers = ['1.1.1.1', '8.8.8.8']
        ips = self.resolve(
            f'dir.{self.network}', force=True
        )
        ips_as_str = [str(ip) for ip in ips]

        global DNS_DIRSERVER_ADDRESSES
        DNS_DIRSERVER_ADDRESSES = ips_as_str

        self.resolver.nameservers = DNS_DIRSERVER_ADDRESSES
        _LOGGER.debug(
            f'Setting nameserver(s) to use to: {DNS_DIRSERVER_ADDRESSES}'
        )
        global DNS_DIRSERVER_EXPIRES
        DNS_DIRSERVER_EXPIRES = datetime.now(tz=timezone.utc)

    def resolve(self, fqdn: str, force: bool = False) -> list[IpAddress]:
        '''
        Looks up the DNS A records for the provided FQDN
        '''

        if not force and DNS_DIRSERVER_EXPIRES < datetime.now(tz=timezone.utc):
            self._update_dirserver_ips()

        ips = []
        try:
            answer = self.resolver.resolve(fqdn)
            for rr in answer.rrset.items:
                try:
                    ip = IpAddress(rr.address)
                    ips.append(ip)
                except ValueError:
                    pass
        except dns.resolver.NXDOMAIN:
            pass

        _LOGGER.debug(
            f'FQDN addresses {fqdn}: {", ".join([str(ip) for ip in ips])}'
        )

        return ips

