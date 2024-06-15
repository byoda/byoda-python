#!/usr/bin/bash

pkill -f pod_worker
rm -f /run/lock/youtube_ingest.lock
cd /podserver/byoda-python
exec nice -20 ionice -c 2 -n 7 pipenv run podserver/pod_worker.py \
    1>${LOGDIR}/worker-stdout.log \
    2>${LOGDIR}/worker-stderr.log &
