#!/bin/bash

export PYTHONPATH=$PYTHONPATH:/podserver/byoda-python:/podserver/bento4/bin

cd /podserver/byoda-python

# Starting BYODA POD using environment variables

cat <<EOF
{
    "settings": {
        "DEBUG": "${DEBUG}",
        "CLOUD": "${CLOUD}",
        "PRIVATE_BUCKET": "${PRIVATE_BUCKET}",
        "RESTRICTED_BUCKET": "${RESTRICTED_BUCKET}",
        "PUBLIC_BUCKET": "${PUBLIC_BUCKET}",
        "LOGLEVEL": "${LOGLEVEL}",
        "LOGDIR": "${LOGDIR}",
        "WORKER_LOGLEVEL": "${WORKER_LOGLEVEL}",
        "PYTHONPATH": "${PYTHONPATH}",
        "NETWORK": "${NETWORK}",
        "ACCOUNT_ID": "${ACCOUNT_ID}",
        "ACCOUNT_USERNAME": "${ACCOUNT_USERNAME}",
        "ACCOUNT_SECRET": "${ACCOUNT_SECRET}",
        "PRIVATE_KEY_SECRET": "${PRIVATE_KEY_SECRET}",
        "BOOTSTRAP": "${BOOTSTRAP}",
        "CUSTOM_DOMAIN": "${CUSTOM_DOMAIN}",
        "SHARED_WEBSERVER": "${SHARED_WEBSERVER}",
        "MANAGE_CUSTOM_DOMAIN_CERT": "${MANAGE_CUSTOM_DOMAIN_CERT}",
        "Let's Encrypt directory": "${LETSENCRYPT_DIRECTORY}",
        "YouTube channel": "${YOUTUBE_CHANNEL}",
        "YouTube polling interval": "${YOUTUBE_IMPORT_INTERVAL}",
        "FastAPI workers": "${WORKERS}"
    }
}
EOF

if [ -z "${LOGDIR}" ]; then
    export LOGDIR='/var/log/byoda'
fi

mkdir -p $LOGDIR
echo "{\"message\": \"Starting bootstrap for podserver\"}"
pipenv run podserver/bootstrap.py

if [[ "$?" != "0" ]]; then
    echo "{\"message\": \"Bootstrap failed\"}"
    FAILURE=1
else
    echo "{\"message\": \"Bootstrap exited successfully\"}"
fi

if [[ -z "${FAILURE}" ]]; then
    echo "{\"message\": \"Starting pod_worker\"}"
    # pod_worker no longer daemonizes itself because of issues between
    # daemon.DaemonContext() and aioschedule
    nice -20 pipenv run podserver/pod_worker.py \
        1>${LOGDIR}/worker-stdout.log \
        2>${LOGDIR}/worker-stderr.log &

    if [[ "$?" != "0" ]]; then
        echo "{\"message\": \"Podworker failed\"}"
        FAILURE=1
    else
        echo "{\"message\": \"Podworker exited successfully\"}"
    fi
fi

if [[ -z "${FAILURE}" ]]; then
    echo "{\"message\": \"Starting feed worker\"}"
    nice -20 pipenv run podserver/feed_worker.py \
        1>${LOGDIR}/feed-stdout.log \
        2>${LOGDIR}/feed-stderr.log &

    if [[ "$?" != "0" ]]; then
        echo "{\"message\": \"Feedworker failed\"}"
        FAILURE=1
    else
        echo "{\"message\": \"Feedworker exited successfully\"}"
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
    echo "{\"message\": \"Starting the web application server\"}"
    pipenv run python3 -m gunicorn \
        -c gunicorn.conf.py \
        podserver.main:app
    if [[ "$?" != "0" ]]; then
        echo "{\"message\": \"Failed to start the application server\"}"
        FAILURE=1
    fi
fi

# Wait for 15 minutes if we crash while running in DEBUG mode
# so the owner of the pod can check the logs
if [[ "${FAILURE}" != "0" && -n "${DEBUG}" ]]; then
    echo "{\"message\": \"Failed, sleeping 900 seconds\"}"
    sleep 900
fi
