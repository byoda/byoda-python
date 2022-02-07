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
echo "BOOTSTRAP: $BOOTSTRAP"

cd /podserver/byoda-python
pipenv run podserver/podworker.py

if [ "${WORKERS}" = "" ]; then
    # BUG: multiple workers will not pick up on new memberships
    # so we set workers to 1
    WORKERS=1
fi

pipenv run python3 -m gunicorn -c gunicorn.conf.py podserver.main:app

# Wait for 15 minutes if we crash so the owner of the pod can check the logs
if [[ "$?" != "0" ]]; then
    echo "Sleeping 900 seconds"
    sleep 900
fi
