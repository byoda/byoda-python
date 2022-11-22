'''
Access for database used for the DNS server. The PowerDNS
DNS software is supported. This class writes to a SQL database
and PowerDNS reads from the database to answer DNS queries.

The DnsDb class does not use any abstraction for different
storage technologies as PowerDNS only supports SQL databases, for
which we have coverage through SQLAlchemy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
import time
from enum import Enum
from uuid import UUID
from ipaddress import ip_address, IPv4Address

from sqlalchemy import MetaData, Table, delete, event, and_
from sqlalchemy import Column, String, Boolean, Integer, BigInteger, ForeignKey
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.future import select
from sqlalchemy import create_engine

from sqlalchemy.engine import Engine
from byoda.secrets import MemberSecret, AccountSecret, ServiceSecret

from byoda.datatypes import IdType

_LOGGER = logging.getLogger(__name__)

DEFAULT_TTL = 1800
DEFAULT_TTL_TXT = 60

DEFAULT_DB_EXPIRE = 7 * 24 * 60 * 60


class DnsRecordType(Enum):
    A = 'A'
    TXT = 'TXT'


class DnsDb:
    '''
    DnsDb manages access to the SQL database storing the DNS records
    for accounts, members and services

    Public properties:
    - domain : the domain for the network, ie. 'byoda.net'
    '''

    def __init__(self, network: str):
        '''

        Constructor for the DnsDb class

        :param network: the domain for the network
        :raises: (none)
        :returns: none)
        '''

        self.domain = network

        self._metadata = MetaData()
        self._engine = None

        self._domain_ids = {}

        # https://docs.sqlalchemy.org/en/14/core/engines.html#dbengine-logging

        logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
        logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
        logging.getLogger('sqlalchemy.dialects').setLevel(logging.WARNING)
        logging.getLogger('sqlalchemy.dialormects').setLevel(logging.WARNING)

        self._domains_table = Table(
            'domains', self._metadata,
            Column('id', Integer),
            Column('name', String(255)),
            Column('master', String(128)),
            Column('last_check', Integer),
            Column('type', String(6)),
            Column('notified_serial', BigInteger),
            Column('account', String(40))
        )
        self._records_table = Table(
            'records', self._metadata,
            Column('id', BigInteger, primary_key=True),
            Column('domain_id', Integer, ForeignKey('domains.id')),
            Column('name', String(255)),
            Column('type', String(10)),
            Column('content', String(65535)),
            Column('ttl', Integer),
            Column('prio', Integer),
            Column('disabled', Boolean),
            Column('ordername', String(255)),
            Column('auth', Boolean),

            Column('db_expire', Integer)
        )

    @staticmethod
    async def setup(connectionstring: str, network_name: str):
        '''
        Factory for DnsDb class

        :param connectionstring: connectionstring for the Postgres DB
        :param network_name: domain for the network, ie. 'byoda.net'
        :returns:
        :raises:

        '''

        dnsdb = DnsDb(network_name)

        dnsdb._engine = create_engine(
                connectionstring, echo=False, isolation_level='AUTOCOMMIT'
            )

        # Ensure the 'accounts' subdomain for the network exists
        subdomain = f'accounts.{network_name}'
        with dnsdb._engine.connect() as conn:
            domain_id = await dnsdb._get_domain_id(conn, subdomain)
            dnsdb._domain_ids[subdomain] = domain_id

        return dnsdb

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

        subdomains = fqdn.split('.')
        if '_' in subdomains[0]:
            # IdType.MEMBER
            uuid, service_id = subdomains[0].split('_')
            uuid = UUID(uuid)
        else:
            if subdomains[0].isdigit():
                # IdType.SERVICE
                uuid = None
                service_id = int(subdomains[0])
            else:
                uuid = UUID(subdomains[0])

        id_type = IdType(subdomains[1])

        return uuid, id_type, service_id

    async def create_update(self, uuid: UUID, id_type: IdType,
                            ip_addr: ip_address,
                            service_id: int = None) -> bool:
        '''
        Create DNS A and optionally a TXT record, replacing any existing DNS
        record.

        :param uuid: account or member. Must be None for IdType.SERVICE
        :param id_type: instance of byoda.datatypes.IdType
        :param ip_addr: client ip
        :param service_id: service identifier
        :returns: whether existing DNS records were updated
        :raises:
        '''

        self._validate_parameters(
            uuid, id_type, ip_addr=ip_addr, service_id=service_id
        )

        db_expire = int(time.time() + DEFAULT_DB_EXPIRE)
        fqdn = self.compose_fqdn(uuid, id_type, service_id=service_id)

        record_replaced = False

        for dns_record_type, value in [
                (DnsRecordType.A, str(ip_addr)), (DnsRecordType.TXT, None)]:
            # TODO: refactor now that we have ruled out Let's Encrypt certs
            # and TXT records
            if not value:
                # No value provided for the DNS record type, ie. no value for
                # secret specified because the IP address is always provided
                continue

            # SQLAlachemy doesn't have 'UPSERT' so we do a lookup, remove if
            # the entry already exists and then create the new record
            try:
                existing_value = await self.lookup(
                    uuid, id_type, dns_record_type, service_id=service_id
                )
                if existing_value and value == str(existing_value):
                    # Nothing to change
                    _LOGGER.debug(
                        f'No DNS changed needed for FQDN {fqdn} with IP '
                        f'{value}'
                    )
                    continue

                record_replaced = record_replaced or await self.remove(
                    uuid, id_type, dns_record_type, service_id=service_id
                )
            except KeyError:
                pass

            with self._engine.connect() as conn:
                # TODO: when we have multiple directory servers, the local
                # 'cache' of domains_id might be out of date
                hostname, subdomain = fqdn.split('.', 1)
                if subdomain not in self._domain_ids:
                    domain_id = await self._upsert_subdomain(conn, subdomain)
                else:
                    domain_id = self._domain_ids[subdomain]

                stmt = insert(
                    self._records_table
                ).values(
                    name=fqdn, content=str(value), domain_id=domain_id,
                    db_expire=db_expire, type=dns_record_type.value,
                    ttl=DEFAULT_TTL, prio=0, auth=True
                )

                conn.execute(stmt)

        return record_replaced

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

        fqdn = self.compose_fqdn(uuid, id_type, service_id)

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
        _LOGGER.debug(f'Performing lookup for {fqdn}')
        with self._engine.connect() as conn:
            _LOGGER.debug(f'Performing lookup for {fqdn}')
            stmt = select(
                self._records_table.c.id, self._records_table.c.content
            ).where(
                and_(
                    self._records_table.c.name == fqdn,
                    self._records_table.c.type == dns_record_type.value
                )
            )

            try:
                _LOGGER.debug(f'Executing SQL command: {stmt}')
                domains = conn.execute(stmt)
            except Exception as exc:
                _LOGGER.error(f'Failed to execute SQL statement: {exc}')
                return

            values = [domain.content for domain in domains]

            if not len(values):
                raise KeyError(
                    f'No {dns_record_type} records found for {fqdn}'
                )

            if len(values) > 1:
                _LOGGER.warning(
                    f'FQDN {fqdn} has more than one {dns_record_type} '
                    f'record: {", ".join(values)}'
                )

        value = values[0]
        if dns_record_type == DnsRecordType.A:
            value = IPv4Address(value)

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

        fqdn = self.compose_fqdn(uuid, id_type, service_id)

        with self._engine.connect() as conn:
            if dns_record_type == DnsRecordType.TXT:
                stmt = delete(
                    self._records_table
                ).where(
                    and_(
                        self._records_table.c.name == fqdn,
                        self._records_table.c.type == dns_record_type.value
                    )
                )
                conn.execute(stmt)
                return True
            else:
                stmt = select(
                    self._records_table.c.id
                ).where(
                    self._records_table.c.name == fqdn
                )
                result = conn.execute(stmt)
                domains = result.fetchall()

                for domain in domains:
                    stmt = delete(
                        self._records_table
                    ).where(
                        and_(
                            self._records_table.c.id == domain.id,
                            self._records_table.c.type == dns_record_type.value
                        )
                    )
                    conn.execute(stmt)

                _LOGGER.debug(
                    f'Removed {len(domains)} DNS record(s) for UUID {uuid} '
                    f'and service_id {service_id}'
                )

            return len(domains) > 0

    async def _get_domain_id(self, conn: Engine, subdomain: str,
                             create_missing: bool = True) -> int:
        '''
        Get the Powerdns domain_id for the subdomain from Postgres

        :param conn: SqlAlchemy Engine
        :param subdomain: string with the domain
        :returns: domain_id
        '''

        if subdomain in self._domain_ids:
            return self._domain_ids[subdomain]

        stmt = select(
            self._domains_table.c.id
        ).where(
            self._domains_table.c.name == subdomain
        )

        domains = conn.execute(stmt)

        first = domains.first()

        if not first:
            if create_missing:
                _LOGGER.info('Creating domain {subdomain} in DnsDB')
                await self._upsert_subdomain(conn, subdomain)
                return await self._get_domain_id(
                    conn, subdomain, create_missing=False
                )
            else:
                raise ValueError(
                    f'Could not find or create ID for domain {subdomain}'
                )
        else:
            domain_id = first.id

        return domain_id

    async def _upsert_subdomain(self, conn: Engine, subdomain: str,
                                ) -> bool:
        '''
        Adds subdomain to list of domains

        :param conn: instance of connection to Postgresql
        :param subdomain: string with the domain to add
        :returns: bool on success
        :raises:
        '''

        if subdomain in self._domain_ids:
            raise ValueError(
                f'Subdomain {subdomain} already has domain id '
                f'{self._domain_ids[subdomain]}'
            )

        stmt = insert(
            self._domains_table
        ).values(
            name=subdomain,
            type='NATIVE'
        ).on_conflict_do_nothing(
            index_elements=['name']
        )
        _LOGGER.debug(f'Upserting domain {subdomain}')
        conn.execute(stmt)

        domain_id = await self._get_domain_id(conn, subdomain)
        self._domain_ids[subdomain] = domain_id

        soa = \
            f'{subdomain} hostmaster.{subdomain} 0 10800 3600 604800 3600'
        stmt = insert(
            self._records_table
        ).values(
            name=subdomain, content=soa,
            domain_id=domain_id,
            type='SOA', ttl=DEFAULT_TTL, prio=0,
            auth=True
        )
        # on_conflict requires a constraint on the 'name' column of the
        # 'records' table
        # on_conflict_stmt = stmt.on_conflict_do_nothing(
        #    index_elements=['name']
        # )
        conn.execute(stmt)

        ns = 'dir.byoda.net.'
        stmt = insert(
            self._records_table
        ).values(
            name='@', content=ns,
            domain_id=domain_id,
            type='NS', ttl=DEFAULT_TTL, prio=0,
            auth=True
        )
        # on_conflict requires a constraint on the 'name' column of the
        # 'records' table
        # on_conflict_stmt = stmt.on_conflict_do_nothing(
        #    index_elements=['name']
        # )

        conn.execute(stmt)

        _LOGGER.debug(
            f'Created subdomain {subdomain} with SOA {soa} and NS {ns}'
        )

        return domain_id

    def _validate_parameters(self, uuid: UUID, id_type: IdType,
                             ip_addr: ip_address = None,
                             service_id: int | None = None):
        '''
        Validate common parameters for DnsDb member functions. Normalize
        data types where appropriate

        :param uuid: account_id or member_id. Can be None for id_type.SERVICE
        :param id_type: account / member / service
        :param service_id: service identifier, required for IdType.SERVICE
        :returns: (None)
        :raises: ValueError
        '''

        if uuid and isinstance(uuid, UUID):
            pass
        elif uuid and isinstance(uuid, str):
            uuid = UUID(uuid)
        elif uuid is not None:
            raise ValueError(f'uuid must be of type UUID, not {type(uuid)}')

        if ip_addr is not None and isinstance(ip_addr, IPv4Address):
            pass
        elif ip_addr is not None and isinstance(ip_addr, str):
            ip_addr = ip_address(ip_addr)
        elif ip_addr is not None:
            raise ValueError('IP address must be of type ip_address or str')

        if not isinstance(id_type, IdType):
            if isinstance(id_type, str):
                id_type = IdType(id_type)
            else:
                raise ValueError(f'Invalid type for id_type: {type(id_type)}')

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

        return


@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context,
                          executemany):
    conn.info.setdefault('query_start_time', []).append(time.time())


@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context,
                         executemany):
    total = time.time() - conn.info['query_start_time'].pop(-1)
    _LOGGER.debug(f'Total time for query {statement}: {total}')
