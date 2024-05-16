#!/usr/bin/bash

# Tool to reload gunicorn processes, which restarts the workers,
# so that log files are re-opened.
# Can be called using:
#   docker exec <container> /podserver/byoda-python/tools/reload-gunicorn.sh
PIDFILE=

# byoda-service
# byoda-byotube-service
if [ -f /run/svcserver.pid ]; then
    PIDFILE=/run/svcserver.pid
fi

# byoda-cdn
if [ -f /run/cdn-server.pid ]; then
    PIDFILE=/run/svcserver.pid
fi

# byoda-cdnapp
if [ -f /run/cdn-server.pid ]; then
    PIDFILE=/run/svcserver.pid
fi

# byoda-directory
if [ -f /run/cdn-server.pid ]; then
    PIDFILE=/run/cdn-server.pid
fi

# byoda-pod
if [ -f /run/podserver.pid ]; then
    PIDFILE=/run/podserver.pid
fi

if [ -z $PIDFILE ]; then
    echo "No PID file found. Exiting."
    exit 1
fi

if [ ! -f $PIDFILE ]; then
    echo "PID file $PIDFILE not found. Exiting."
    exit 1
fi

PID=$(cat $PIDFILE)

echo "Sending HUP signal to $PID, found in $PIDFILE"

kill -HUP $PID

