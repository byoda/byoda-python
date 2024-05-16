'''
Class for SQL tables used for BYO.Tube-lite service


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import os

from typing import Self

os.environ['PSYCOPG_IMPL'] = 'binary'
from psycopg_pool import AsyncConnectionPool        # noqa: E402
from psycopg.rows import dict_row                   # noqa: E402
from psycopg import AsyncCursor                     # noqa: E402
from psycopg.errors import CheckViolation           # noqa: E402
from psycopg.errors import UniqueViolation          # noqa: E402


class SqlStorage:
    def __init__(self, connection_string: str) -> None:
        self.connection_string: str = connection_string
        self.pool: AsyncConnectionPool | None = None

    async def setup(connection_string: str) -> Self:
        sql = SqlStorage(connection_string)
        sql.pool = AsyncConnectionPool(
            conninfo=sql.connection_string, open=False,
            kwargs={'row_factory': dict_row}
        )
        await sql.pool.open()

        return sql

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def query(self, stmt: str, params: dict,
                    fetch_some: bool | None = None) -> int | dict | list[dict]:
        '''
        Executes a query on the database. We use for row_factory the dict_row, so
        we may return one dict or a list of dicts, depending on the fetch_some
        parameter

        :param stmt:
        :param params:
        :param fetch_some: should results be returned: None for no,
        False for 1, True for all
        :returns: If fetch_some is None, returns the number of rows affected,
        if fetch_some is False, returns the first row, if fetch_some is True,
        :returns: number of rows affected, the first row, or all rows
        '''

        try:
            async with self.pool.connection() as conn:
                result: AsyncCursor[dict] = await conn.execute(stmt, params)
        except (CheckViolation, UniqueViolation) as exc:
            raise ValueError(exc)

        if fetch_some is None:
            return result.rowcount
        if fetch_some is False:
            return await result.fetchone()

        return await result.fetchall()


ACCOUNT_STATUSES_STMTS: dict[str, str] = {
    'create': '''
    CREATE TABLE IF NOT EXISTS account_statuses(
        status_id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
        lite_id uuid NOT NULL,
        status TEXT NOT NULL,
        timestamp 0 TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
        reason TEXT
        comment TEXT
        CONSTRAINT account_exists FOREIGN_KEY(lite_id) REFERENCES accounts(lite_id) ON DELETE CASCADE,
    );
    CREATE INDEX IF NOT EXISTS status_lite_id_index ON account_statuses(lite_id);
    CREATE INDEX IF NOT EXISTS status_reason_index ON account_statuses(comment);
'''
}

# The company handling the financial transaction
PAYMENT_PROCESSOR_STMTS: dict[str, str] = {
    'create': '''
    CREATE TABLE IF NOT EXISTS payment_processors(
        processor_id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
        country_code: TEXT NOT NULL,
        name TEXT NOT NULL,
        enabled BOOL DEFAULT TRUE,
        CONSTRAINT processor_name UNIQUE(name, country_code)
    );
'''
}

# A payment account of the user, ie. a credit card or a bank account
# supporting ACH
PAYMENT_ACCOUNTS_STMTS: dict[str, str] = {
    'create': '''
    CREATE TABLE IF NOT EXISTS payment_accounts(
        payment_account_id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
        lite_id uuid NOT NULL,
        alias TEXT,
        hint: TEXT,
        enabled: BOOL DEFAULT TRUE,
        account_type: TEXT NOT NULL,
        balance DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
        currency: TEXT NOT NULL DEFAULT 'USD',
        account_details_protected: BLOB NOT NULL,
        type: TEXT,
        status: TEXT,
        CONSTRAINT account_exists FOREIGN_KEY(lite_id) REFERENCES accounts(lite_id) ON DELETE CASCADE,
    );
    CREATE INDEX IF NOT EXISTS payment_lite_id_index ON payment_accounts(lite_id);
'''
}

# A payment transaction from user to byo.tube
PAYMENTS_STMTS: dict[str, str] = {
    'create': '''
    CREATE TABLE IF NOT EXISTS account_payments(
        payment_id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
        payment_account_id uuid NOT NULL,
        payment_processor_id uuid NOT NULL,
        amount DECIMAL(10, 2) NOT NULL,
        currency TEXT NOT NULL DEFAULT 'USD',
        timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
        CONSTRAINT payment_account_exists FOREIGN_KEY(payment_account_id) REFERENCES payment_accounts(payment_account_id) ON DELETE CASCADE,
        CONSTRAINT payment_processor_exists FOREIGN_KEY(payment_processor_id) REFERENCES payment_processors(processor_id) ON DELETE SET NULL,
    );
'''
}

PAYMENT_STATUSES_STMTS: dict[str, str] = {
    'create': '''
    CREATE TABLE IF NOT EXISTS payment_statuses(
        status_id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
        timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        payment_id uuid NOT NULL,
        status TEXT NOT NULL,
        reason TEXT,
        comment TEXT,
        CONSTRAINT payment_exists FOREIGN_KEY(payment_id) REFERENCES account_payments(payment_id) ON DELETE CASCADE,
    );
    CREATE INDEX IF NOT EXISTS payment_status_status_index ON payment_statuses(status);
'''
}

# NETWORK_LINKS_STMTS: dict[str, str] = {
#     'create': '''
#     CREATE TABLE IF NOT EXISTS network_links(
#         link_id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
#         lite_id uuid NOT NULL,
#         created_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
#         member_id uuid NOT NULL,
#         relation TEXT NOT NULL,
#         creator TEXT NOT NULL,
#         CONSTRAINT account_exists FOREIGN_KEY(lite_id) REFERENCES accounts(lite_id) ON DELETE CASCADE,
#     );
#     CREATE INDEX IF NOT EXISTS network_lunk_lite_id_index ON network_links(lite_id);
#     CREATE INDEX IF NOT EXISTS network_link_member_id_index ON network_links(network_id);
#     CREATE INDEX IF NOT EXISTS network_link_creator_index ON network_links(network_id);
# '''
# }

# ASSET_REACTIONS_STMTS: dict[str, str] = {
#     'create': '''
#     CREATE TABLE IF NOT EXISTS
#     '''
# }