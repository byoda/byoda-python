#!/usr/bin/env python3

import logging
import asyncio

from gql import Client, gql
from gql.transport.websockets import WebsocketsTransport


logging.basicConfig(level=logging.INFO)


async def main():
    ws_url = 'ws://127.0.0.1:8000/graphql'
    transport = WebsocketsTransport(url=ws_url)

    # Using `async with` on the client will start a connection on the transport
    # and provide a `session` variable to execute queries on this connection
    async with Client(
        transport=transport,
        fetch_schema_from_transport=True,
    ) as session:

        # Request subscription
        subscription = gql(
            """
            subscription {
                person {
                    User {
                        name
                        age
                    }
                }
            }
        """
        )
        async for result in session.subscribe(subscription):
            print(result)


if __name__ == '__main__':
    asyncio.run(main())
    #unittest.main()