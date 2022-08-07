#!/bin/bash

export PYTHONPATH=$PYTHONPATH:/podserver/byoda-python

# Start nginx first
nginx

if [ "${WORKERS}" = "" ]; then
    # BUG: multiple workers will not pick up on new memberships
    # so we set workers to 1
    WORKERS=1
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
echo "CUSTOM_DOMAIN: ${CUSTOM_DOMAIN}"
echo "FastAPI workers: ${WORKERS}"

cd /podserver/byoda-python

if [[ -n "${CUSTOM_DOMAIN}" ]]; then
    if [[ -f "/etc/letsencrypt/live/${CUSTOM_DOMAIN}/privkey.pem" ]]; then
        # Certbot will only call Let's Encrypt APIs if cert is due for renewal
        pipenv run certbot renew
    else
        pipenv run certbot certonly --webroot -w /var/www/wwwroot/ -n --agree-tos -m postmaster@${CUSTOM_DOMAIN} -d ${CUSTOM_DOMAIN}
    fi
fi

pipenv run podserver/podworker.py

PODWORKER_FAILURE=$?
if [[ "$?" == "0" ]]; then
  echo "Podworker exited successfully"
  # location of pid file is used by byoda.util.reload.reload_gunicorn
  rm -rf /var/run/podserver.pid
  pipenv run python3 -m gunicorn -p /var/run/podserver.pid --error-logfile /var/www/wwwroot/logs/gunicorn-error.log --access-logfile /var/www/wwwroot/logs/gunicorn-access.log -c gunicorn.conf.py podserver.main:app
else
  echo "Podworker failed"
  SLEEP=1
fi

# Wait for 15 minutes if we crash so the owner of the pod can check the logs
if [[ "$?" != "0" ]]; then
    SLEEP=1
fi

if [[ "${SLEEP}" != "0" ]]; then
    echo "Sleeping 900 seconds"
    sleep 900
fi
