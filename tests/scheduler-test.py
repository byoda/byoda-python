#!/usr/bin/env python3

import sys
import time
import daemon

import asyncio

from schedule import every, repeat, run_pending


async def main(argv):
    with daemon.DaemonContext():
        while True:
            with open('/tmp/schedule.out', 'a') as file_desc:
                file_desc.write('Running pending tasks\n')
            run_pending()
            time.sleep(3)


@repeat(every(5).seconds)
def log_ping_message():
    with open('/tmp/schedule.out', 'a') as file_desc:
        file_desc.write('Log worker ping message\n')


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
