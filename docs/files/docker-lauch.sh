#!/bin/bash

# set -x

DOCKER=$(which docker)

if [ $? -ne 0 ]; then
    echo "Docker binary not found, please install it"
    exit 1
fi

ACCOUNT_FILE=~/.byoda-account_id
if [ -f "${ACCOUNT_FILE}" ]; then
    ACCOUNT_ID=$(cat ~/.byoda-account_id)
    echo "Reading account_id from ${ACCOUNT_FILE}: ${ACCOUNT_ID}"
else
    ACCOUNT_ID=$(uuid -v 4)
    if [ $? -ne 0 ]; then
        echo "Failed to run 'uuid', please install it"
        exit 1
    fi
    echo $ACCOUNT_ID >~/.byoda-account_id
    echo "Writing account_id to ${ACCOUNT_FILE}: ${ACCOUNT_ID}"
fi

if [ -f ~/src/byoda-python/byoda/servers/pod_server.py ]; then
    export PORT=$(grep HTTP_PORT ~/src/byoda-python/byoda/servers/pod_server.py | cut -d ' ' -f 7)
else
    export PORT=8000
fi

SYSTEM_MFCT=$(sudo dmidecode -t system | grep Manufacturer)
SYSTEM_VERSION=$(sudo dmidecode -t system | grep Version)
echo "System manufacturer: ${SYSTEM_MFCT}, version: ${SYSTEM_VERSION}"

if [[ "${SYSTEM_MFCT}" == *"Microsoft Corporation"* ]]; then
    export CLOUD=Azure
    echo "Running in cloud: ${CLOUD}"
elif [[ "${SYSTEM_MFCT}" == *"Google"* ]]; then
    export CLOUD=GCP
    echo "Running in cloud: ${CLOUD}"
elif [[ "${SYSTEM_VERSION}" == *"amazon"* ]]; then
    export CLOUD=AWS
    echo "Running in cloud: ${CLOUD}"
else
    export CLOUD=LOCAL
    echo "Not runing in a public cloud"
fi

export ROOT_DIR=/byoda
export LOGLEVEL=DEBUG
export BOOTSTRAP=BOOTSTRAP

sudo docker stop byoda
sudo docker rm byoda
# sudo docker rmi byoda/byoda-pod:latest
sudo rm -rf ${ROOT_DIR}
sudo mkdir -p ${ROOT_DIR}
echo "Creating container for account_id ${ACCOUNT_ID}"
docker pull byoda/byoda-pod:latest
sudo docker run -d \
    --name byoda \
    -p 443:443 -p 2222:22 -p ${PORT}:${PORT} \
    -e "CLOUD=${CLOUD}" \
    -e "BUCKET_PREFIX=byoda" \
    -e "NETWORK=byoda.net" \
    -e "ACCOUNT_ID=${ACCOUNT_ID}" \
    -e "ACCOUNT_SECRET=supersecret" \
    -e "LOGLEVEL=${LOGLEVEL}" \
    -e "PRIVATE_KEY_SECRET=byoda" \
    -e "PYTHONPATH=/home/steven/src/byoda-python" \
    -e "BOOTSTRAP=BOOTSTRAP" \
    -e "ROOT_DIR=${ROOT_DIR}" \
    -v ${ROOT_DIR}:${ROOT_DIR} \
    byoda/byoda-pod:latest
