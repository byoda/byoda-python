#!/bin/bash

export PYTHONPATH=$PYTHONPATH:/podserver/byoda-python

cd /podserver/byoda-python

# Make sure an account exists
tools/account_exists.py 2>/var/www/wwwroot/logs/account_exists.log

nginx

/usr/sbin/sshd -E /tmp/sshd.log &

# Starting BYODA POD using environment variables

echo "CLOUD: $CLOUD"
echo "BUCKET_PREFIX: $BUCKET_PREFIX"
echo "LOGLEVEL: $LOGLEVEL"
echo "PYTHONPATH: $PYTHONPATH"
echo "NETWORK: $NETWORK"
echo "ACCOUNT_ID: $ACCOUNT_ID"
echo "ACCOUNT_SECRET $ACCOUNT_SECRET"
echo "PRIVATE_KEY_SECRET: $PRIVATE_KEY_SECRET"

gunicorn --chdir /podserver/byoda-python -c /podserver/byoda-python/gunicorn.conf.py --pythonpath /podserver/byoda-python podserver.main:app 2>/var/www/wwwroot/logs/gunicorn.log

if [[ "$?" != "0" ]]; then
    echo "Sleeping 900 seconds"
    sleep 900
    echo "Running bash for debugging purposes"
    bash
fi
