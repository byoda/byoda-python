'''
Access for database used for the DNS server. The PowerDNS
DNS software is supported. This class writes to a SQL database
and PowerDNS reads from the database to answer DNS queries.

The DnsDb class does not use any abstraction for different
storage technologies as PowerDNS only supports SQL databases, for
which we have coverage through SQLAlchemy

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
import time
from uuid import UUID
from ipaddress import ip_address, IPv4Address

from sqlalchemy import MetaData, Table, insert, delete, event
from sqlalchemy.future import select
from sqlalchemy.engine import Engine

from byoda.datatypes import IdType

_LOGGER = logging.getLogger(__name__)

DEFAULT_TTL = 1800
DEFAULT_DB_EXPIRE = 7 * 24 * 60 * 60


class DnsDb:
    '''
    DnsDb manages access to the SQL database storing the DNS records
    for accounts, members and services

    Public properties:
    - domain : the domain for the network, ie. 'byoda.net'
    '''

    def __init__(self, network_name: str):
        '''

        Constructor for the DnsDb class

        :param network_name: the domain for the network
        :raises: (none)
        :returns: none)
        '''

        self.domain = network_name

        self._metadata = MetaData()
        self._engine = None
        self._domains_table = None
        self._records_table = None

        self._domain_ids = {}

    @staticmethod
    def setup(connectionstring: str, network_name: str):
        '''
        Factory for DnsDb class

        :param connectionstring: connectionstring for the Postgres DB
        :param network_name: domain for the network, ie. 'byoda.net'
        :returns:
        :raises:

        '''

        dnsdb = DnsDb(network_name)

        # https://docs.sqlalchemy.org/en/14/core/engines.html#dbengine-logging

        logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
        logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
        logging.getLogger('sqlalchemy.dialects').setLevel(logging.WARNING)
        logging.getLogger('sqlalchemy.dialormects').setLevel(logging.WARNING)

        # TODO: figure out why asynchpg is not working
        if False and 'asyncpg' in connectionstring:
            from sqlalchemy.ext.asyncio import create_async_engine
            dnsdb._engine = create_async_engine(
                connectionstring, echo=False, future=True,
                isolation_level='AUTOCOMMIT'
            )
        else:
            from sqlalchemy import create_engine
            dnsdb._engine = create_engine(
                connectionstring + '?async_fallback=true',
                echo=False, future=True, isolation_level='AUTOCOMMIT'
            )

        with dnsdb._engine.connect() as conn:
            dnsdb._domains_table = Table(
                'domains', dnsdb._metadata, autoload_with=dnsdb._engine
            )
            dnsdb._records_table = Table(
                'records', dnsdb._metadata, autoload_with=dnsdb._engine
            )

            for subdomain in ('accounts', 'services', 'members'):
                domain_id = dnsdb._get_domain_id(
                    conn, f'{subdomain}.{network_name}'
                )
                dnsdb._domain_ids[subdomain] = domain_id

        return dnsdb

    def compose_fqdn(self, uuid: UUID, id_type: IdType, service_id: int = None
                     ) -> str:
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
            return f'{str(uuid)}_{service_id}.{id_type.value}.{self.domain}'
        elif id_type == IdType.ACCOUNT:
            return f'{str(uuid)}.{id_type.value}.{self.domain}'
        elif id_type == IdType.SERVICE:
            return f'{str(service_id)}.{id_type.value}.{self.domain}'

    def decompose_fqdn(self, fqdn: str) -> (UUID, IdType, int):
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

    def create_update(self, uuid: UUID, id_type: IdType,
                      ip_addr: ip_address, service_id: int = None) -> bool:
        '''
        Create DNS record, replacing any existing DNS record

        :param uuid: account or member. Must be None for IdType.SERVICE
        :param id_type: instance of byoda.datatypes.IdType
        :param ip_addr: client ip
        :param service_id: service identifier
        :returns: whether one or more DNS records were updated
        :raises:
        '''

        self._validate_parameters(
            uuid, id_type, ip_addr=ip_addr, service_id=service_id
        )

        try:
            ip_replaced = False
            existing_ip_address = self.lookup(
                uuid, id_type, service_id=service_id
            )
            if ip_addr == existing_ip_address:
                return 0

            if existing_ip_address:
                ip_replaced = self.remove(
                    uuid, id_type, service_id=service_id
                )
        except KeyError:
            pass

        fqdn = self.compose_fqdn(uuid, id_type, service_id=service_id)

        db_expire = int(time.time() + DEFAULT_DB_EXPIRE)
        with self._engine.connect() as conn:
            stmt = insert(
                self._records_table
            ).values(
                name=fqdn, content=str(ip_addr),
                domain_id=self._domain_ids[id_type.value],
                db_expire=db_expire,
                type='A', ttl=DEFAULT_TTL, prio=0, auth=True
            )

            conn.execute(stmt)

        return ip_replaced

    def lookup(self, uuid: UUID, id_type: IdType, service_id: int = None
               ) -> ip_address:
        '''
        Look up the DNS record for the UUID, which is either an
        account_id, a member_id or a service_id

        :param uuid: instance of uuid.UUID
        :param id_type: instance of byoda.datatypes.IdType
        :returns: IP address found for the lookup
        :raises: KeyError if DNS record for the uuid could not be found
        '''

        self._validate_parameters(uuid, id_type, service_id=service_id)

        fqdn = self.compose_fqdn(uuid, id_type, service_id)

        ip_addr = None
        with self._engine.connect() as conn:
            stmt = select(
                self._records_table.c.id, self._records_table.c.content
            ).where(
                self._records_table.c.name == fqdn
            )
            _LOGGER.debug(f'Executing SQL command: {stmt}')

            domains = conn.execute(stmt)

            ips = [domain.content for domain in domains]

            if not len(ips):
                raise KeyError(f'No IP address found for {fqdn}')

            if len(ips) > 1:
                _LOGGER.warning(
                    f'FQDN {fqdn} has more than one IP address: '
                    f'{", ".join(ips)}'
                )

            ip_addr = ip_address(ips[0])

        return ip_addr

    def remove(self, uuid: UUID, id_type: IdType, service_id=None) -> bool:
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
            stmt = select(
                self._records_table.c.id
            ).where(
                self._records_table.c.name == fqdn
            )
            domains = conn.execute(stmt).fetchall()

            for domain in domains:
                stmt = delete(
                    self._records_table
                ).where(
                    self._records_table.c.id == domain.id
                )
                conn.execute(stmt)

            _LOGGER.debug(
                f'Removed {len(domains)} DNS record(s) for UUID {uuid}'
            )

        return len(domains) > 0

    def _validate_parameters(self, uuid: UUID, id_type: IdType,
                             ip_addr: ip_address = None, service_id=None):
        '''
        Validate common parameters for DnsDb member functions. Normalize
        data types where appropriate

        :param uuid: client
        :param id_type: account / member / service
        :param service_id: service identifier, required for IdType.service
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

    def _get_domain_id(self, conn: Engine, subdomain: str):
        '''
        Get the Powerdns domain_id for the subdomain from Postgres

        :param conn: sqlalchemy connection instance
        :param subdomain: string with the domain
        :returns: integer with the domain_id
        :raises: ValueError if the domain can not be found
        '''

        stmt = select(
            self._domains_table.c.id
        ).where(
            self._domains_table.c.name == subdomain
        )

        domains = conn.execute(stmt)
        domain_id = domains.first().id

        if not domain_id:
            raise ValueError(f'Could not find ID for domain {subdomain}')

        return domain_id


@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context,
                          executemany):
    conn.info.setdefault('query_start_time', []).append(time.time())


@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context,
                         executemany):
    total = time.time() - conn.info['query_start_time'].pop(-1)
    _LOGGER.debug(f'Total time for query {statement}: {total}')
