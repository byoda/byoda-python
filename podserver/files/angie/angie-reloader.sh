#!/bin/bash

LOGFILE=/var/log/byoda/angie-reloader.out

while true; do
    # install inotifywait with: apt install inotify-tools
    inotifywait --exclude .swp -e create -e modify -e delete -e move -r /etc/angie/conf.d
    angie -t
    if [ $? -eq 0 ]; then
        echo "Detected Angie Configuration Change"
        echo "Executing: angie -s reload"
        angie -s reload
    fi
done
