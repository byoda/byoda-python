#!/bin/bash

# set -x
# export DOCKER_BUILD_KIT=1

if [ ! -d .git ]; then
    echo "Must be run from a git directory"
    exit 1
fi

if [ -z "${TAG}" ]; then
    RESULT=$(git status | grep 'branch main')

    if [ "$?" -eq "0" ]; then
        export TAG=latest
    else
        export TAG=dev
    fi
fi

echo "Using tag: ${TAG}"

NAME=$1

TARGET=

# POD
if [[ "${NAME}" == "pod" || "${NAME}" == "p" ]]; then
    TARGET="pod"
fi

# Directory service
if [[ "${NAME}" == "dir" || "${NAME}" == "byoda-directory" || "${NAME}" == "d" ]]; then
    TARGET="directory"
fi

# BYODA Service
if [[ "${NAME}" == "svc" || "${NAME}" == "byoda-svc" || "${NAME}" == "s" ]]; then
    TARGET="service"
fi

# BYO.Tube service
if [[ "${NAME}" == "b" || "${NAME}" == "t" || "${NAME}" == "byotube" || "${NAME}" == "tube" ]]; then
    TARGET="byotube-service"
fi

# BYO.Tube asset updates worker
if [[ "${NAME}" == "svcassetupdatesworker" || "${NAME}" == "updates" || "${NAME}" == "u" ]]; then
    TARGET="service-asset-updates-worker"
fi

# BYO.Tube asset refresh worker
if [[ "${NAME}" == "svcassetrefreshworker" || "${NAME}" == "refresh" || "${NAME}" == "r" ]]; then
    TARGET="service-asset-refresh-worker"
fi

# BYO.Tube channel refresh worker
if [[ "${NAME}" == "svcchannelrefreshworker" || "${NAME}" == "channel" || "${NAME}" == "cr" || "${NAME}" == "c" ]]; then
    TARGET="service-channel-refresh-worker"
fi

# BYO.Tube email worker
if [[ "${NAME}" == "e" || "${NAME}" == "email" ]]; then
    TARGET="service-email-worker"
fi

# Generic BYODA application server
if [[ "${NAME}" == "a" || "${NAME}" == "byoda-app" || "${NAME}" == "app" || "${NAME}" == "w" ]]; then
    TARGET="app"
fi

if [ -z "${TARGET}" ]; then
    echo "Must specify a target: ${NAME}"
    exit 1
fi

TARGETS="pod service service-asset-updates-worker service-asset-refresh-worker service-email-worker directory service-channel-refresh-worker byotube-service app"
if echo "${TARGETS}" | grep -qw "${TARGET}"; then
    echo "Building docker container for byoda-${TARGET} with TAG ${TAG} with docker file Dockerfile-${TARGET}"
else
    echo "Invalid target: ${TARGET}"
    exit 1
fi

docker build . --file Dockerfile-${TARGET} --tag byoda/byoda-${TARGET}:${TAG} --build-arg TAG=${TAG}

if [ "$?" -eq "0" ]; then
    export IMAGE_ID=$(docker images --format='{{.ID}}'  | head -1)
    echo "Pushing image: $IMAGE_ID"
    docker image tag ${IMAGE_ID} byoda/byoda-${TARGET}:${TAG}
    docker push byoda/byoda-${TARGET}:${TAG}
    echo "Docker build completed"
else
    echo "Docker build failed"
fi

