#!/bin/bash

export PYTHONPATH=$PYTHONPATH:/podserver/byoda-python

cd /podserver/byoda-python

nginx

if [ -f /usr/sbin/sshd ]; then
    /usr/sbin/sshd -E /tmp/sshd.log &
fi

# Starting BYODA POD using environment variables

echo "CLOUD: $CLOUD"
echo "BUCKET_PREFIX: $BUCKET_PREFIX"
echo "LOGLEVEL: $LOGLEVEL"
echo "PYTHONPATH: $PYTHONPATH"
echo "NETWORK: $NETWORK"
echo "ACCOUNT_ID: $ACCOUNT_ID"
echo "ACCOUNT_SECRET $ACCOUNT_SECRET"
echo "PRIVATE_KEY_SECRET: $PRIVATE_KEY_SECRET"

podserver/podworker.py

if [ "${WORKERS}" = "" ]; then
    WORKERS=2
fi

uvicorn --chdir /podserver/byoda-python --port 8001 --workers ${WORKERS} --no-use-colors --proxy-headers --forwarded-allow-ips 127.0.0.1 podserver.main:app

# Wait for 15 minutes if we crash so the owner of the pod can check the logs
if [[ "$?" != "0" ]]; then
    echo "Sleeping 900 seconds"
    sleep 900
fi
