#!/bin/bash

LOGFILE=/var/log/byoda/angie-reloader.out

while true; do
   inotifywait --exclude .swp -e create -e modify -e delete -e move -r /etc/angie/conf.d
   angie -t
   if [ $? -eq 0 ]; then
       echo "Detected Angie Configuration Change"
       echo "Executing: nginx -s reload"
       angie -s reload
   fi
done
