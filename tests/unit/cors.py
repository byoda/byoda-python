import unittest

import httpx

from starlette.middleware import Middleware
from starlette_context import plugins
from starlette_context.middleware import RawContextMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient

from fastapi import FastAPI

origins: list[str] = [
    "http://localhost.tiangolo.com",
    "https://localhost.tiangolo.com",
    "http://localhost",
    "http://localhost:8080",
]

middleware: list[Middleware] = [
    Middleware(
        CORSMiddleware, allow_origins=origins,
        allow_credentials=True, allow_methods=['*'],
        allow_headers=['*'], expose_headers=['*'], max_age=86400
    ),
    Middleware(
        RawContextMiddleware,
        plugins=(
            plugins.RequestIdPlugin(),
            plugins.CorrelationIdPlugin()
        )
    )
]

APP = FastAPI(middleware=middleware)


@APP.get("/")
async def main() -> dict[str, str]:
    return {"message": "Hello World"}


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    def test_service_get(self) -> None:
        location: str = 'http://localhost'
        headers: dict[str, str] = {
            'Origin': location,
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': 'content-type, blah'
        }
        with TestClient(APP, headers=headers) as client:
        # with httpx.Client(app=APP) as client:
            API: str = 'http://localhost/'
            resp: httpx.Response = client.get(API, headers=headers)
            self.assertEqual(resp.status_code, 200)
            check_cors_headers(self, resp, False, location)


def check_cors_headers(testcase, resp: httpx.Response, is_preflight: bool,
                       location: str) -> None:
    testcase.assertEqual(
        resp.headers['access-control-allow-origin'], location
    )
    testcase.assertEqual(
        resp.headers['access-control-allow-credentials'], 'true'
    )
    testcase.assertEqual(
        resp.headers['vary'], 'Origin'
    )

    if not is_preflight:
        return

    testcase.assertEqual(
        resp.headers['access-control-allow-methods'],
        'DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT'
    )
    testcase.assertEqual(resp.headers['access-control-max-age'], '86400')

    testcase.assertEqual(
        resp.headers['access-control-allow-headers'], 'content-type'
    )

    return


if __name__ == '__main__':
    unittest.main()