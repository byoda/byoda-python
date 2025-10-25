'''
Access for database used for the DNS server. The PowerDNS
DNS software is supported. This class writes to a SQL database
and PowerDNS reads from the database to answer DNS queries.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

import time

from enum import Enum
from uuid import UUID
from typing import Self
from logging import Logger
from logging import getLogger
from ipaddress import ip_address
from ipaddress import IPv4Address

import orjson

from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
from psycopg import AsyncCursor
from psycopg.types.json import set_json_dumps
from psycopg.types.json import set_json_loads

from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.account_secret import AccountSecret
from byoda.secrets.service_secret import ServiceSecret

from byoda.datatypes import IdType

_LOGGER: Logger = getLogger(__name__)

DEFAULT_FQDN_TTL = 1800
DEFAULT_DOMAIN_TTL = 86400
DEFAULT_TTL_TXT = 60


NAMESERVER_FQDNS: list[str] = [
    'ns-va-01.byoda.net', 'ns-va-02.byoda.net'
]

DEFAULT_DB_EXPIRE = 7 * 24 * 60 * 60


class DnsRecordType(Enum):
    A = 'A'
    TXT = 'TXT'


class DnsSql:
    STMTS: dict[str, str] = {
        'get_domain': '''
            SELECT id
            FROM domains
            WHERE name=%(name)s
        ''',
        'get_record': '''
            SELECT id, domain_id, type, content
            FROM records
            WHERE name=%(name)s AND type=%(type)s
        ''',
        'upsert_domain': '''
            INSERT INTO domains (name, type)
            VALUES (%(name)s, 'NATIVE')
            ON CONFLICT DO NOTHING
            RETURNING id
        ''',
        'upsert_record': '''
            INSERT INTO records (
                    name, content, domain_id, type, ttl,
                    prio, auth, db_expire
                )
            VALUES(
                %(name)s, %(content)s, %(domain_id)s,
                %(record_type)s, %(ttl)s, 0, True, %(db_expire)s
            )
            ON CONFLICT ON CONSTRAINT records_unique
            DO UPDATE SET (
                name, content, domain_id, type, ttl, prio, auth
            ) = (
                %(name)s, %(content)s, %(domain_id)s, %(record_type)s,
                %(ttl)s, 0, True
            )
            RETURNING id
        ''',
        'delete_record': '''
            DELETE FROM records
            WHERE name=%(name)s AND type=%(type)s
        '''
    }


class DnsDb:
    '''
    DnsDb manages access to the SQL database storing the DNS records
    for accounts, members and services

    Public properties:
    - domain : the domain for the network, ie. 'byoda.net'
    '''

    def __init__(self, network: str, nameservers: list[str] = NAMESERVER_FQDNS
                 ) -> None:
        '''

        Constructor for the DnsDb class

        :param network: the domain for the network
        :raises: (none)
        :returns: none)
        '''

        self.domain: str = network
        self.nameservers: list[str] = nameservers

        # A cache so we don't have to look up the domain_id every
        # time we want to upsert a new record
        self._domain_ids: dict[str, int] = {}

        self.connection_string: str = ''

        self.pool: AsyncConnectionPool | None = None

    @staticmethod
    async def setup(connectionstring: str, network_name: str) -> Self:
        '''
        Factory for DnsDb class

        :param connectionstring: connectionstring for the Postgres DB
        :param network_name: domain for the network, ie. 'byoda.net'
        :returns:
        :raises:

        '''

        self = DnsDb(network_name)
        set_json_dumps(orjson.dumps)
        set_json_loads(orjson.loads)

        self.connection_string = connectionstring
        self.pool = AsyncConnectionPool(
            conninfo=self.connection_string, open=False,
            kwargs={'row_factory': dict_row, 'autocommit': True}
        )
        await self.pool.open()

        # Ensure the 'accounts' subdomain for the network exists
        subdomain: str = f'accounts.{network_name}'
        domain_id: int = await self._get_domain_id(subdomain, True)
        self._domain_ids[subdomain] = domain_id
        return self

    async def close(self) -> None:
        '''
        Close the connection pool

        :returns: (none)
        :raises: (none)
        '''

        if self.pool:
            await self.pool.close()
            self.pool = None

    async def _upsert_domain(self, subdomain: str) -> int:
        '''
        Ensure the specified subdomain exists in the DnsDB

        :param subdomain: string with the subdomain to upsert
        :returns: domain_id for the subdomain
        :raises:
        '''

        if not self.pool:
            raise RuntimeError('Connection pool is not initialized')

        if subdomain in self._domain_ids:
            raise ValueError(
                f'Subdomain {subdomain} already has domain id '
                f'{self._domain_ids[subdomain]}'
            )

        _LOGGER.debug(f'Upserting domain {subdomain}')
        async with self.pool.connection() as conn:
            result: AsyncCursor[dict] = await conn.execute(
                DnsSql.STMTS['upsert_domain'], {'name': subdomain}
            )
            if not result.rowcount:
                domain_id: int = await self._get_domain_id(subdomain, False)
                self._domain_ids[subdomain] = domain_id
                _LOGGER.debug(
                    f'Domain {subdomain} already exists in DnsDB '
                    f'in row {domain_id}'
                )
                return domain_id

            domain_id: int = (await result.fetchone())['id']
            self._domain_ids[subdomain] = domain_id

            soa_data: str = \
                f'{subdomain} hostmaster.{subdomain} 0 10800 3600 604800 3600'

            result: AsyncCursor[dict] = await conn.execute(
                DnsSql.STMTS['upsert_record'],
                {
                    'name': subdomain,
                    'content': soa_data,
                    'domain_id': domain_id,
                    'record_type': 'SOA',
                    'ttl': DEFAULT_DOMAIN_TTL,
                    'db_expire': int(time.time()) + DEFAULT_DB_EXPIRE
                }
            )

            if not result.rowcount:
                raise RuntimeError(
                    f'Failed to upsert SOA record for domain {subdomain}'
                )

            result = await conn.execute(
                DnsSql.STMTS['upsert_record'],
                {
                    'name': subdomain,
                    'content': self.nameservers[0],
                    'domain_id': domain_id,
                    'record_type': 'NS',
                    'ttl': DEFAULT_DOMAIN_TTL,
                    'db_expire': 0
                }
            )

            if not result.rowcount:
                raise RuntimeError(
                    f'Failed to upsert NS record for domain {subdomain}'
                )

            result = await conn.execute(
                DnsSql.STMTS['upsert_record'],
                {
                    'name': subdomain,
                    'content': self.nameservers[1],
                    'domain_id': domain_id,
                    'record_type': 'NS',
                    'ttl': DEFAULT_DOMAIN_TTL,
                    'db_expire': 0
                }
            )

            await conn.commit()

            if not result.rowcount:
                raise RuntimeError(
                    f'Failed to upsert NS record for domain {subdomain}'
                )

        _LOGGER.debug(
            f'Created subdomain {subdomain} with SOA {soa_data} and NS for '
            f'{",".join(self.nameservers)}'
        )

        return domain_id

    async def create_update(self, uuid: UUID, id_type: IdType,
                            ip_addr: ip_address,
                            service_id: int = None) -> None:
        '''
        Create or update a DNS A record, replacing any existing DNS data
        for that record

        :param uuid: account or member. Must be None for IdType.SERVICE
        :param id_type:
        :param ip_addr: client ip
        :param service_id: service identifier
        :returns: whether new DNS records were added, with other words
        True: new record added, False: existing record updated
        :raises:
        '''

        self._validate_parameters(
            uuid, id_type, ip_addr=ip_addr, service_id=service_id
        )

        db_expire = int(time.time() + DEFAULT_DB_EXPIRE)
        fqdn: str = self.compose_fqdn(uuid, id_type, service_id=service_id)

        subdomain: str = fqdn.split('.', 1)[1]
        if subdomain not in self._domain_ids:
            domain_id: bool = await self._upsert_domain(subdomain)
        else:
            domain_id = self._domain_ids[subdomain]

        async with self.pool.connection() as conn:
            await conn.execute(
                DnsSql.STMTS['upsert_record'],
                {
                    'name': fqdn,
                    'content': str(ip_addr),
                    'domain_id': domain_id,
                    'record_type': DnsRecordType.A.value,
                    'ttl': DEFAULT_FQDN_TTL,
                    'db_expire': db_expire
                }
            )
            await conn.commit()

    async def lookup(self, uuid: UUID, id_type: IdType,
                     dns_record_type: DnsRecordType, service_id: int = None
                     ) -> ip_address:
        '''
        Look up in DnsDB the DNS record for the UUID, which is either an
        account_id, a member_id or a service_id

        :param uuid: instance of uuid.UUID
        :param id_type: instance of byoda.datatypes.IdType
        :param dns_record_type: type of DNS record to look up
        :param service_id: the identifier for the service
        :returns: IP address found for the lookup in DnsDB
        :raises: KeyError if DNS record for the uuid could not be found
        '''

        self._validate_parameters(uuid, id_type, service_id=service_id)

        fqdn: str = self.compose_fqdn(uuid, id_type, service_id)

        return await self.lookup_fqdn(fqdn, dns_record_type)

    async def lookup_fqdn(self, fqdn: str, dns_record_type: DnsRecordType,
                          ) -> ip_address:
        '''
        Looks up FQDN in the DnsDB

        :param fqdn: FQDN to look up
        :param dns_record_type: what type of DNS record to look up
        :returns: IP address found for the lookup in DnsDB
        :raises: KeyError if DNS record for the uuid could not be found
        '''

        value = None
        _LOGGER.debug(f'Performing lookup for {dns_record_type.value} {fqdn}')
        async with self.pool.connection() as conn:
            try:
                result: AsyncCursor = await conn.execute(
                    DnsSql.STMTS['get_record'],
                    {'name': fqdn, 'type': dns_record_type.value}
                )
            except Exception as e:
                _LOGGER.error(
                    f'Error DNS DB lookup for {fqdn} of '
                    f'type {dns_record_type.value}: {e}'
                )
                raise

            rows: list[dict] = await result.fetchall()
            _LOGGER.debug(f'Found {len(rows)} records for {fqdn}')
            if not rows:
                raise KeyError(
                    f'No {dns_record_type.value} records found for {fqdn}'
                )

            if len(rows) > 1:
                _LOGGER.warning(
                    f'FQDN {fqdn} has more than one {dns_record_type} '
                    f'record: {len(rows)} records found'
                )

        if dns_record_type == DnsRecordType.A:
            value = IPv4Address(rows[0]['content'])

        _LOGGER.debug(f'Found DNS record for {fqdn}: {value}')

        return value

    async def remove(self, uuid: UUID, id_type: IdType,
                     dns_record_type: DnsRecordType, service_id=None) -> bool:
        '''
        Removes the DNS records for the uuid

        :param uuid: client
        :param id_type: account / member / service
        :param service_id: service identifier, required for IdType.service
        :returns: bool on whether one or more records were removed
        '''

        self._validate_parameters(uuid, id_type, service_id=service_id)

        fqdn: str = self.compose_fqdn(uuid, id_type, service_id)

        async with self.pool.connection() as conn:
            result: AsyncCursor = await conn.execute(
                DnsSql.STMTS['delete_record'],
                {'name': fqdn, 'type': dns_record_type.value}
            )

            _LOGGER.debug(
                f'Removed {result.rowcount} DNS record(s) for FQDN {fqdn} '
            )

            return result.rowcount > 0

    async def _get_domain_id(self, subdomain: str,
                             create_missing: bool = True) -> int:
        '''
        Get the Powerdns domain_id for the subdomain from Postgres

        :param subdomain: string with the domain
        :returns: domain_id
        '''

        if not self.pool:
            raise RuntimeError('Connection pool is not initialized')

        if subdomain in self._domain_ids:
            return self._domain_ids[subdomain]

        async with self.pool.connection() as conn:
            result: AsyncCursor[dict] = await conn.execute(
                DnsSql.STMTS['get_domain'], {'name': subdomain}
            )

        if not result.rowcount:
            if not create_missing:
                raise ValueError(f'Domain {subdomain} not found in DnsDB')
            _LOGGER.info(f'Creating domain {subdomain} in DnsDB')
            domain_id: int = await self._upsert_domain(subdomain)
            return domain_id

        if result.rowcount > 1:
            _LOGGER.error(f'More than one domain found for {subdomain}')

        row: dict | None = await result.fetchone()

        if not row:
            raise RuntimeError(f'Failed to fetch data for {subdomain}')

        domain_id: int = row['id']
        self._domain_ids[subdomain] = domain_id

        return domain_id

    def compose_fqdn(self, uuid: UUID, id_type: IdType,
                     service_id: int | None = None) -> str:
        '''
        Generate the FQDN for an id of the specified type

        :param uuid: identifier for the account or member. Must be None for
            IdType.SERVICE
        :param id_type: type of service
        :param service_id: identifier for the service, required for
            IdType.MEMBER and IdType.ACCOUNT
        :returns: FQDN
        :raises: (none)
        '''

        self._validate_parameters(uuid, id_type, service_id=service_id)

        if id_type == IdType.MEMBER:
            return MemberSecret.create_commonname(
                uuid, service_id, self.domain
            )
        elif id_type == IdType.ACCOUNT:
            return AccountSecret.create_commonname(uuid, self.domain)
        elif id_type == IdType.SERVICE:
            return ServiceSecret.create_commonname(service_id, self.domain)

    def decompose_fqdn(self, fqdn: str) -> tuple[UUID, IdType, int]:
        '''
        Get the uuid, the id type and, if applicable the service id from the
        FQDN

        :param str fqdn: FQDN to decompose
        :returns: uuid: uuid, id_type:IdType and service_id:int
        :raises: ValueError if the FQDN does not have the correct format
        '''

        subdomains: list[str] = fqdn.split('.')
        if '_' in subdomains[0]:
            # IdType.MEMBER
            service_id: int = int(subdomains[0].split('_')[1])
            uuid = UUID(subdomains[0].split('_')[0])
        else:
            if subdomains[0].isdigit():
                # IdType.SERVICE
                uuid = None
                service_id = int(subdomains[0])
            else:
                uuid = UUID(subdomains[0])

        id_type = IdType(subdomains[1])

        return uuid, id_type, service_id

    def _validate_parameters(self, uuid: UUID, id_type: IdType,
                             ip_addr: ip_address = None,
                             service_id: int | None = None) -> None:
        '''
        Validate common parameters for DnsDb member functions. Normalize
        data types where appropriate

        :param uuid: account_id or member_id. Can be None for id_type.SERVICE
        :param id_type: account / member / service
        :param service_id: service identifier, required for IdType.SERVICE
        :returns: (None)
        :raises: ValueError
        '''

        uuid = self._validate_parameters_uuid(uuid)

        ip_addr = self._validate_parameters_ipaddr(ip_addr)

        id_type = self._validate_parameters_id_type(id_type, uuid, service_id)

    def _validate_parameters_id_type(self, id_type: IdType, uuid: UUID,
                                     service_id: int | None = None) -> IdType:

        if not isinstance(id_type, IdType):
            if isinstance(id_type, str):
                try:
                    id_type = IdType(id_type)
                except ValueError as exc:
                    raise ValueError(f'Invalid IdType string: {id_type}') from exc
            else:
                raise ValueError(f'Invalid type for id_type: {type(id_type)}')

        return self._validate_parameters_id_type_logic(
            id_type, uuid, service_id
        )

    def _validate_parameters_id_type_logic(self, id_type: IdType, uuid: UUID,
                                           service_id: int | None = None
                                           ) -> IdType:
        '''
        Validate the logic of the id_type, uuid and service_id parameters
        '''
        if id_type == IdType.SERVICE and uuid is not None:
            raise ValueError('uuid must be None for IdType.SERVICE')

        if id_type == IdType.SERVICE and service_id is None:
            raise ValueError('service_id must be specified for IdType.SERVICE')

        if id_type == IdType.ACCOUNT and service_id is not None:
            raise ValueError(
                'service_id must not be specified for IdType.ACCOUNT'
            )

        if id_type == IdType.ACCOUNT and uuid is None:
            raise ValueError(
                'uuid must be specified for IdType.ACCOUNT'
            )

        if id_type == IdType.MEMBER and (uuid is None or service_id is None):
            raise ValueError(
                'uuid and service_id must both be specified for IdType.MEMBER'
            )

        return id_type

    def _validate_parameters_uuid(self, uuid: UUID) -> UUID:
        '''
        Validate and normalize the uuid parameter

        :param uuid: uuid to validate
        :returns: normalized uuid
        :raises: ValueError
        '''

        if uuid is None or isinstance(uuid, UUID):
            return uuid
        elif isinstance(uuid, str):
            try:
                return UUID(uuid)
            except ValueError as e:
                raise ValueError(f'Invalid UUID string: {uuid}') from e
        else:
            raise ValueError(f'Invalid type for uuid: {type(uuid)}')

    def _validate_parameters_ipaddr(self, ip_addr: ip_address
                                    ) -> ip_address:
        '''
        Validate and normalize the ip_addr parameter

        :param ip_addr: ip address to validate
        :returns: normalized ip address
        :raises: ValueError
        '''

        if ip_addr is None or isinstance(ip_addr, (IPv4Address)):
            return ip_addr
        elif isinstance(ip_addr, str):
            try:
                return ip_address(ip_addr)
            except ValueError as e:
                raise ValueError(f'Invalid IP address string: {ip_addr}') from e
        else:
            raise ValueError(f'Invalid type for ip_addr: {type(ip_addr)}')
