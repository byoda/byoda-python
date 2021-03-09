#!/bin/bash

BYODA_NETWORK="byoda.net"

args=$(getopt -l "help" -l "network:"  -o "hn:" -- "$@")

eval set -- "$args"

while [ $# -ge 1 ]; do
    case "$1" in
        --)
            # No more options left.
            shift
            break
            ;;
        -n|--network)
            BYODA_NETWORK=$2
            shift
            ;;
        -h|--help)
            echo "$0: Set up BYODA directory tree"
            echo ""
            echo "Set up the BYODA directory tree in the specified location."
            echo "The target directory can be either specified as command-"
            echo "parameter or using the BYODA_DIR environment variable"
            echo ""
            echo "Usage: $0 [--help/-h] [--network/-n network] <directory>"
            echo ""
            echo "--help/-h                 shows this helptext"
            echo "--network/-n <network>    specifies the name of the network, defaults to 'byoda.net'"
            echo ""
            return 0
            ;;
        *)
           BYODA_DIR=$1
           ;;
    esac
    shift
done

echo "Creating BYODA directory tree at ${BYODA_DIR} for network ${BYODA_NETWORK}"

mkdir -p ${BYODA_DIR}/private
chmod 700 ${BYODA_DIR}/private

mkdir -p ${BYODA_DIR}/network-${BYODA_NETWORK}/services/service-default/
cp services/default.json ${BYODA_DIR}/network-${BYODA_NETWORK}/services/service-default/service-default.json

mkdir -p ${BYODA_DIR}/network-${BYODA_NETWORK}/services/service-addressbook/
cp services/default.json ${BYODA_DIR}/network-${BYODA_NETWORK}/services/service-addressbook/addressbook.json

