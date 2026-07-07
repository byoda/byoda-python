'''
Test helper for running Postgres in a local Docker container.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2026
:license    : GPLv3
'''

import atexit
import os
import socket
import subprocess
import time

from pathlib import Path

from psycopg import connect
from psycopg import Connection
from psycopg import sql


POSTGRES_IMAGE: str = os.getenv(
    'BYODA_TEST_POSTGRES_IMAGE', 'postgres:17-alpine'
)
POSTGRES_USER: str = os.getenv('BYODA_TEST_POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD: str = os.getenv('BYODA_TEST_POSTGRES_PASSWORD', 'byoda')
POSTGRES_DB: str = os.getenv('BYODA_TEST_POSTGRES_DB', 'byoda_pod_test')

_CONTAINER_NAME: str = f'byoda-func-postgres-{os.getpid()}'
_POSTGRES_PORT: int | None = None


def postgres_connection_string(db: str = POSTGRES_DB) -> str:
    '''
    Return a Postgres URL for the local test container.
    '''

    port: int = ensure_postgres_server()
    return (
        f'postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}'
        f'@127.0.0.1:{port}/{db}'
    )


def setup_powerdns_database(db: str = 'byodadns') -> str:
    '''
    Create a fresh PowerDNS database and load the checked-in schema.
    '''

    port: int = ensure_postgres_server()
    admin_connection_string: str = (
        f'postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}'
        f'@127.0.0.1:{port}/postgres'
    )

    conn: Connection = connect(admin_connection_string, autocommit=True)
    try:
        conn.execute(
            sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(
                sql.Identifier(db)
            )
        )
        conn.execute(
            sql.SQL('CREATE DATABASE {}').format(sql.Identifier(db))
        )
    finally:
        conn.close()

    db_connection_string: str = postgres_connection_string(db)
    conn = connect(db_connection_string, autocommit=True)
    try:
        schema: str = Path(
            'docs/infrastructure/powerdns-schema.psql'
        ).read_text()
        schema = schema.replace(
            'CHECK (((name)::TEXT = LOWER((name)::TEXT)))\n'
            '  CONSTRAINT',
            'CHECK (((name)::TEXT = LOWER((name)::TEXT))),\n'
            '  CONSTRAINT'
        )
        for stmt in schema.split(';'):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
    finally:
        conn.close()

    return db_connection_string


def ensure_postgres_server() -> int:
    '''
    Start Postgres if it is not already running for this test process.
    '''

    global _POSTGRES_PORT

    if _POSTGRES_PORT is not None:
        return _POSTGRES_PORT

    port: int = _find_free_port()
    _remove_container()
    subprocess.run(
        [
            'docker', 'run', '--detach', '--rm',
            '--name', _CONTAINER_NAME,
            '--publish', f'127.0.0.1:{port}:5432',
            '--env', f'POSTGRES_USER={POSTGRES_USER}',
            '--env', f'POSTGRES_PASSWORD={POSTGRES_PASSWORD}',
            POSTGRES_IMAGE,
            '-c', 'fsync=off',
            '-c', 'full_page_writes=off',
            '-c', 'synchronous_commit=off',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    _POSTGRES_PORT = port
    atexit.register(_remove_container)
    _wait_for_postgres(port)

    return port


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _wait_for_postgres(port: int) -> None:
    deadline: float = time.monotonic() + 30
    last_error: Exception | None = None
    connection_string: str = (
        f'postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}'
        f'@127.0.0.1:{port}/postgres'
    )

    while time.monotonic() < deadline:
        conn: Connection | None = None
        try:
            conn = connect(connection_string, autocommit=True)
            conn.execute('SELECT 1')
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
        finally:
            if conn:
                conn.close()

    raise RuntimeError(
        f'Postgres test container {_CONTAINER_NAME} did not become ready'
    ) from last_error


def _remove_container() -> None:
    subprocess.run(
        ['docker', 'rm', '--force', _CONTAINER_NAME],
        check=False,
        capture_output=True,
        text=True,
    )
