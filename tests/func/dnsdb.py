#!/usr/bin/env python3

'''
Test the DnsDB class against Postgres server for byoda.net
'''

import sys
import yaml
import time
from uuid import uuid4
from ipaddress import ip_address
import unittest

import dns.resolver

from byoda.util import Logger

from byoda.datatypes import IdType

from byoda.datastore.dnsdb import DnsDb


TEST_DIR = '/tmp/byoda-func-test-secrets'
NETWORK = 'byoda.net'
DNS_CACHE_PERIOD = 300


class TestDnsDb(unittest.TestCase):
    def test_dnsdb(self):
        with open('config.yml') as file_desc:
            config = yaml.load(file_desc, Loader=yaml.SafeLoader)

        dnsdb = DnsDb.setup(
            config['dirserver']['dnsdb'], config['application']['network']
        )

        # SERVICE
        uuid = uuid4()
        service_id = 9999
        first_ip = ip_address('10.255.255.254')

        service_fqdn = dnsdb.compose_fqdn(
            None, IdType.SERVICE, service_id=service_id
        )
        self.assertEqual(service_fqdn, f'{str(service_id)}.services.byoda.net')

        with self.assertRaises(KeyError):
            dnsdb.lookup(None, IdType.SERVICE, service_id=service_id)

        dnsdb.create_update(
            None, IdType.SERVICE, first_ip, service_id=service_id
        )
        self.assertEqual(
            dnsdb.lookup(None, IdType.SERVICE, service_id=service_id), first_ip
        )

        dnsdb.remove(None, IdType.SERVICE, service_id=service_id)

        with self.assertRaises(KeyError):
            dnsdb.lookup(None, IdType.SERVICE, service_id=service_id)

        # MEMBER
        uuid = uuid4()
        member = dnsdb.compose_fqdn(uuid, IdType.MEMBER, service_id=service_id)
        self.assertEqual(
            member, f'{str(uuid)}_{service_id}.members.byoda.net'
        )

        with self.assertRaises(KeyError):
            dnsdb.lookup(uuid, IdType.MEMBER, service_id=service_id)

        dnsdb.create_update(
            uuid, IdType.MEMBER, first_ip, service_id=service_id
        )

        self.assertEqual(
            dnsdb.lookup(uuid, IdType.MEMBER, service_id=service_id), first_ip
        )

        dnsdb.remove(uuid, IdType.MEMBER, service_id=service_id)

        with self.assertRaises(KeyError):
            dnsdb.lookup(uuid, IdType.MEMBER, service_id=service_id)

        # ACCOUNT: we test these last as
        uuid = uuid4()
        account = dnsdb.compose_fqdn(uuid, IdType.ACCOUNT)
        self.assertEqual(account, f'{str(uuid)}.accounts.byoda.net')

        with self.assertRaises(KeyError):
            dnsdb.lookup(uuid, IdType.ACCOUNT)

        fqdn = dnsdb.compose_fqdn(uuid, IdType.ACCOUNT)

        dnsdb.create_update(uuid, IdType.ACCOUNT, first_ip)
        self.assertEqual(first_ip, dnsdb.lookup(uuid, IdType.ACCOUNT))

        dns_ip = do_dns_lookup(fqdn)
        self.assertEqual(dns_ip, first_ip)

        second_ip = ip_address('10.255.255.255')
        dnsdb.create_update(uuid, IdType.ACCOUNT, second_ip)
        self.assertEqual(second_ip, dnsdb.lookup(uuid, IdType.ACCOUNT))

        time.sleep(DNS_CACHE_PERIOD + 1)

        dns_ip = do_dns_lookup(fqdn)
        self.assertEqual(dns_ip, second_ip)

        # TODO Packet and record caching of PowerDNS likely makes this test
        # fail

        # time.sleep(DNS_CACHE_PERIOD + 1)
        # with self.assertRaises(dns.resolver.NXDOMAIN):
        #    do_dns_lookup(fqdn)


def do_dns_lookup(fqdn):
    resolver = dns.resolver.Resolver()
    resolver.nameservers = ['104.42.73.223']        # dir.byoda.net
    resolver.timeout = 1
    resolver.lifetime = 1

    answer = resolver.query(fqdn)
    dns_ip = ip_address(list(answer.rrset.items.keys())[0].address)

    return dns_ip


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
