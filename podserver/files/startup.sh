#!/bin/bash

export PYTHONPATH=$PYTHONPATH:/podserver/byoda-python

cd /podserver/byoda-python

# Starting BYODA POD using environment variables

echo "DEBUG: $DEBUG"
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
echo "SHARED_WEBSERVER: ${SHARED_WEBSERVER}"
echo "MANAGE_CUSTOM_DOMAIN_CERT: ${MANAGE_CUSTOM_DOMAIN_CERT}"
echo "Let's Encrypt directory: ${LETSENCRYPT_DIRECTORY}"
echo "Twitter username: ${TWITTER_USERNAME}"
echo "Twitter API KEY: ${TWITTER_API_KEY}"
echo "FastAPI workers: ${WORKERS}"

# First see if we need to generate or renew a Let's Encrypt certificate
if [[ -n "${CUSTOM_DOMAIN}" && -n "${MANAGE_CUSTOM_DOMAIN_CERT}" ]]; then
    if [[ -f "/etc/letsencrypt/live/${CUSTOM_DOMAIN}/privkey.pem" ]]; then
        # Certbot will only call Let's Encrypt APIs if cert is due for renewal
        # With the '--standalone' option, certbot will run its own HTTP webserver
        echo "Running certbot to renew the certificate for custom domain ${CUSTOM_DOMAIN}"
        pipenv run certbot renew --standalone
    else
        echo "Generating a Let's Encrypt certificate for custom domain ${CUSTOM_DOMAIN}"
        # With the '--standalone' option, certbot will run its own HTTP webserver
        pipenv run certbot certonly --standalone -n --agree-tos -m postmaster@${CUSTOM_DOMAIN} -d ${CUSTOM_DOMAIN}
    fi
fi

if [[ "$?" != "0" ]]; then
    echo "Certbot failed, exiting"
    FAILURE=1
fi

# Start nginx first
if [[ -z "${FAILURE}" && -z "${SHARED_WEBSERVER}" ]]; then
    echo "Starting nginx"
    nginx
fi

if [[ "$?" != "0" ]]; then
    echo "Nginx failed to start"
    FAILURE=1
fi

if [[ -z "${FAILURE}" ]]; then
    echo "Starting bootstrap for podserver"
    pipenv run podserver/bootstrap.py

    if [[ "$?" != "0" ]]; then
        echo "Bootstrap failed"
        FAILURE=1
    else
        echo "Bootstrap exited successfully"
    fi
fi

if [[ -z "${FAILURE}" ]]; then
    echo "Starting podworker"
    # podworker no longer daemonizes itself because of issues between
    # daemon.DaemonContext() and aioschedule
    pipenv run podserver/podworker.py 2>/var/www/wwwroot/logs/podworker-stderr.log 1>/var/www/wwwroot/logs/podworker-stdout.log &

    if [[ "$?" != "0" ]]; then
        echo "Podworker failed"
        FAILURE=1
    else
        echo "Podworker exited successfully"
    fi
fi

if [ "${WORKERS}" = "" ]; then
    # BUG: multiple workers will not pick up on new memberships
    # so we set workers to 1
    export WORKERS=1
fi

if [[ -z "${FAILURE}" ]]; then
    # location of pid file is used by byoda.util.reload.reload_gunicorn
    rm -rf /var/run/podserver.pid
    echo "Starting the web application server"
    pipenv run python3 -m gunicorn -p /var/run/podserver.pid --error-logfile /var/www/wwwroot/logs/gunicorn-error.log --access-logfile /var/www/wwwroot/logs/gunicorn-access.log -c gunicorn.conf.py podserver.main:app
    if [[ "$?" != "0" ]]; then
        echo "Failed to start the application server"
        FAILURE=1
    fi
fi

# Wait for 15 minutes if we crash while running in DEBUG mode
# so the owner of the pod can check the logs
if [[ "${FAILURE}" != "0" && -n "${DEBUG}" ]]; then
    echo "Failed, sleeping 900 seconds"
    sleep 900
fi
