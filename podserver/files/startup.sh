#!/bin/bash

export PYTHONPATH=$PYTHONPATH:/podserver/byoda-python

cd /podserver/byoda-python

# Make sure an account exists
tools/account_exists.py

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

gunicorn --chdir /podserver/byoda-python -c /podserver/byoda-python/gunicorn.conf.py --pythonpath /podserver/byoda-python podserver.main:app

if [[ "$?" != "0" ]]; then
    echo "Sleeping 900 seconds"
    sleep 900
fi
