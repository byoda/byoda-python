'''
Gunicorn acts as process manager for uvicorn. Gunicorn does not support ASGI,
uvicorn does

Supported environment variables:
  - WORKERS: number of processes to be launched by gunicorn, defaults to 2.
    Setting it to 0 will cause workers to be launched based on the number of
    cores in the pod

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import multiprocessing

# Sample config file:
# https://gist.github.com/HacKanCuBa/275bfca09d614ee9370727f5f40dab9e

# BIND parameter is set in systemd file

forwarded_allow_ips = os.environ.get('TRUSTED_IP', '127.0.0.1')

workers = os.environ.get('WORKERS', 2)

if workers == 0:
    workers = multiprocessing.cpu_count() * 2 + 1

worker_class = "uvicorn.workers.UvicornWorker"
