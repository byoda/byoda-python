#!/bin/bash

# set -x
export DOCKER_BUILD_KIT=1

if [ ! -d .git ]; then
    echo "Must be run from a git directory"
    exit 1
fi

NAME=$1

TARGET=

DOCKER=docker
#DOCKER=/home/steven/bin/nerdctl

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

# Angie
if [[ "${NAME}" == "angie" ]]; then
    TARGET="angie"
    ANGIE_TAG=latest
    ${DOCKER} build . --file Dockerfile-${TARGET} --tag byoda/${TARGET}:${ANGIE_TAG} --build-arg TAG=${ANGIE_TAG}
    if [ "$?" -eq "0" ]; then
        export IMAGE_ID=$(${DOCKER} images --format='{{.ID}}'  | head -1)
        echo "Pushing image: $IMAGE_ID"
        ${DOCKER} image tag ${IMAGE_ID} byoda/${TARGET}:${ANGIE_TAG}
        ${DOCKER} push byoda/${TARGET}:${ANGIE_TAG}
        echo "Docker build of Angie completed"
        exit 0
    else
        echo "Docker build of Angie failed"
        exit 1
    fi
fi

if [ -z "${TARGET}" ]; then
    echo "Must specify a target: ${NAME}"
    exit 1
fi


if [ -z "${TAG}" ]; then
    RESULT=$(git status | grep 'branch main')
    if [ "$?" -eq "0" ]; then
        export TAG=latest
    else
        if [[ "${TARGET}" == "pod" || "${TARGET}" == "p" ]]; then
            # For now we always build latest if TAG is not specified
            # because k8s only supports always_pull for tag 'latest'
            # export TAG=dev
            export TAG=latest
        else
            export TAG=latest
        fi
    fi
fi

echo "Using tag: ${TAG}"

TARGETS="pod service service-asset-updates-worker service-asset-refresh-worker service-email-worker directory service-channel-refresh-worker byotube-service app"
if echo "${TARGETS}" | grep -qw "${TARGET}"; then
    echo "Building container for byoda-${TARGET} with TAG ${TAG} using Dockerfile-${TARGET}"
else
    echo "Invalid target: ${TARGET}"
    exit 1
fi

${DOCKER} build . --file Dockerfile-${TARGET} --tag byoda/byoda-${TARGET}:${TAG} --build-arg TAG=${TAG}

if [ "$?" -eq "0" ]; then
    export IMAGE_ID=$(${DOCKER} images --format='{{.ID}}'  | head -1)
    echo "Pushing image: $IMAGE_ID"
    ${DOCKER} image tag ${IMAGE_ID} byoda/byoda-${TARGET}:${TAG}
    ${DOCKER} push byoda/byoda-${TARGET}:${TAG}
    echo "Docker build completed"
else
    echo "Docker build failed"
fi

