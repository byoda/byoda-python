'''
Provides an postgresql+asyncpg session to a route

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

from sqlalchemy.ext.asyncio import AsyncSession

from byoda.datastore.dnsdb import DnsDb

from byoda import config


async def asyncdb_session() -> AsyncSession:
    dnsdb: DnsDb = config.server.network.dnsdb

    async with dnsdb.async_session() as session:
        yield session
