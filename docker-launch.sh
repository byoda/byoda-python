#!/bin/bash

source ~/.bash_aliases

export TAG=latest

if [ -z "$1" ]; then
    echo "Usage: $0 <container-name>"
    exit 1
fi

export SERVICE_ID=16384
if [ -n "$2" ]; then
    export SERVICE_ID=$2
fi

CONTAINER=$(get_container $1)

TARGETS="byoda-directory byoda-service byoda-worker byoda-moderate"
if echo "${TARGETS}" | grep -qw "${CONTAINER}"; then
    echo "Launching docker container for ${CONTAINER}"
else
    echo "Invalid target: ${CONTAINER}"
    exit 1
fi

export BYODA_HOME=/opt/byoda
export BYODA_DOMAIN=byoda.net
export LOG_DIR=/var/log/byoda
export CONFIG_FILE=${BYODA_HOME}/config.yml

ERROR="0"
if [ "${CONTAINER}" == "byoda-worker" ]; then
    export PORTMAP=""
    export CONTAINER="byoda-serviceworker"
    export HOSTCONTAINER="byoda-worker"
    export SERVICE_DIR="service-${SERVICE_ID}"
    export CONFIG_FILE=${BYODA_HOME}/service-16384/config.yml
    sudo rm "${LOG_DIR}/worker-${SERVICE_ID}.log"
elif [ "${CONTAINER}" == "byoda-directory" ]; then
    export PORTMAP="-p 8030:8000"
    export HOSTCONTAINER="byoda-directory"
    export SERVICE_DIR="dirserver"
    export CONFIG_FILE="${BYODA_HOME}/dirserver/config.yml"
elif [ "${CONTAINER}" == "byoda-service" ]; then
    # We need to make sure the file for the unprotected key exists, otherwise
    # docker will volume mount it as a directory
    sudo touch /var/tmp/service-${SERVICE_ID}.key
    sudo chown root:root /var/tmp/service-${SERVICE_ID}.key

    if [ "$SERVICE_ID" == "16384" ]; then
        export PORTMAP="-p 8010:8000"
    else
        export PORTMAP="-p 8011:8000"
    fi
    export HOSTCONTAINER="byoda-$SERVICE_ID"
    export SERVICE_DIR="service-${SERVICE_ID}"
    export CONFIG_FILE=${BYODA_HOME}/service-${SERVICE_ID}/config.yml
elif [ "${CONTAINER}" == "byoda-moderate" ]; then
    export HOSTCONTAINER="${CONTAINER}"
    export CONTAINER="byoda-app"
    export PORTMAP="-p 8020:8000"
    export SERVICE_DIR="modtest"
else
    echo "Unknown container: ${CONTAINER}"
    exit 1
fi

docker rm --force ${HOSTCONTAINER}

if [ "${CONTAINER}" != "byoda-moderate" ]; then
  echo "SERVER_CONTAINER=$HOSTCONTAINER.${BYODA_DOMAIN}" 
  echo /var/log/byoda:/var/log/byoda 
  echo ${BYODA_HOME}/${SERVICE_DIR}:${BYODA_HOME}/${SERVICE_DIR}
  echo ${CONFIG_FILE}:/podserver/byoda-python/config.yml
  echo byoda/${CONTAINER}:${TAG}
  docker run -d \
    --name ${HOSTCONTAINER} \
    --restart=unless-stopped \
    --pull always \
    ${PORTMAP} \
    -e "LOGLEVEL=INFO" \
    -e "WORKERS=2" \
    -e "SERVER_CONTAINER=$HOSTCONTAINER.${BYODA_DOMAIN}" \
    -v /var/log/byoda:/var/log/byoda \
    -v ${BYODA_HOME}/${SERVICE_DIR}:${BYODA_HOME}/${SERVICE_DIR} \
    -v ${CONFIG_FILE}:/podserver/byoda-python/config.yml \
    byoda/${CONTAINER}:${TAG}
#    -v ${CONFIG_FILE}:${BYODA_HOME}/byoda-python/config.yml \
else
  docker run -d \
    --name ${HOSTCONTAINER} \
    --restart=unless-stopped \
    --pull always \
    ${PORTMAP} \
    -e "LOGLEVEL=INFO" \
    -e "WORKERS=2" \
    -e "SERVER_CONTAINER=$HOSTCONTAINER.${BYODA_DOMAIN}" \
    -v /var/log/byoda:/var/log/byoda \
    -v /var/tmp:/var/tmp \
    -v ${BYODA_HOME}/${SERVICE_DIR}:${BYODA_HOME}/${SERVICE_DIR} \
    -v ${BYODA_HOME}/config.yml:/podserver/byoda-python/config.yml \
    -v /usr/share/nginx/mod:/usr/share/nginx/mod \
    byoda/${CONTAINER}:${TAG}
fi

