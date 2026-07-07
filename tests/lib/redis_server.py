'''
Test helper for running Redis Stack in a local Docker container.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2026
:license    : GPLv3
'''

import atexit
import os
import socket
import subprocess
import time

from urllib.parse import urlencode

from redis import Redis


REDIS_IMAGE: str = os.getenv(
    'BYODA_TEST_REDIS_IMAGE', 'redis/redis-stack-server:latest'
)

_CONTAINER_NAME: str = f'byoda-unit-redis-{os.getpid()}'
_REDIS_PORT: int | None = None


def redis_url(db: int = 0, *, decode_responses: bool = False,
              protocol: int = 3) -> str:
    '''
    Return a Redis URL for the local Redis Stack test container.
    '''

    port: int = ensure_redis_server()
    query: dict[str, str | int] = {'protocol': protocol}
    if decode_responses:
        query['decode_responses'] = 'True'

    return f'redis://127.0.0.1:{port}/{db}?{urlencode(query)}'


def flush_redis(db: int = 0) -> None:
    '''
    Flush the requested Redis DB in the local Redis Stack test container.
    '''

    client: Redis = Redis.from_url(redis_url(db), protocol=3)
    try:
        client.flushdb()
    finally:
        client.close()


def ensure_redis_server() -> int:
    '''
    Start Redis Stack if it is not already running for this test process.
    '''

    global _REDIS_PORT

    if _REDIS_PORT is not None:
        return _REDIS_PORT

    port: int = _find_free_port()
    _remove_container()
    subprocess.run(
        [
            'docker', 'run', '--detach', '--rm',
            '--name', _CONTAINER_NAME,
            '--publish', f'127.0.0.1:{port}:6379',
            REDIS_IMAGE,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    _REDIS_PORT = port
    atexit.register(_remove_container)
    _wait_for_redis(port)

    return port


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _wait_for_redis(port: int) -> None:
    deadline: float = time.monotonic() + 30
    last_error: Exception | None = None
    url: str = f'redis://127.0.0.1:{port}/0?protocol=3'

    while time.monotonic() < deadline:
        client: Redis = Redis.from_url(url, protocol=3)
        try:
            client.ping()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
        finally:
            client.close()

    raise RuntimeError(
        f'Redis test container {_CONTAINER_NAME} did not become ready'
    ) from last_error


def _remove_container() -> None:
    subprocess.run(
        ['docker', 'rm', '--force', _CONTAINER_NAME],
        check=False,
        capture_output=True,
        text=True,
    )
