#!/bin/bash

sh -c "angie-reloader.sh &"
exec "$@"
