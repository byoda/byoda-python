#!/usr/bin/bash

# Sets environment variables to facilitate using curl to tell the pod to do things

# maintainer : Steven Hessing <steven@byoda.org>
# copyright  : Copyright 2021, 2022, 2023, 2024
# license    : GPLv3


PARAM=$_
COMMAND=$0

if [[ "${PARAM}" == "${COMMAND}" ]]; then
    echo "$COMMAND: This script must be sourced instead of executed, e.g. 'source $COMMAND'"
    exit 1
fi

if [ -f  ${HOME}/byoda-generic-settings.sh ]; then
    echo "Loading settings from ${HOME}/byoda-generic-settings.sh"
    source ${HOME}/byoda-generic-settings.sh
fi

if [ -f ${HOME}/byoda-settings.sh ]; then
    echo "Loading settings from ${HOME}/byoda-settings.sh"
    source ${HOME}/byoda-settings.sh
fi

if [ -f  ${HOME}/byoda-user-settings.sh ]; then
    echo "Loading settings from ${HOME}/byoda-user-settings.sh"
    source ${HOME}/byoda-user-settings.sh
fi

export PYTHONPATH=$PYTHONPATH:$(pwd):~/byoda-python:~/src/byoda-python:/root/byoda-python:/root/src/byoda-python
export NETWORK="byoda.net"

export POSTFIX=
if [[ ${HOSTNAME:0:4} == "byo-" ]]; then
    export POSTFIX=$HOSTNAME
fi
if [[ ${HOSTNAME} == 'dathes' || ${HOSTNAME} == 'notest' || ${HOSTNAME} == 'demotest' || ${HOSTNAME} == 'dmz' ]]; then
    export POSTFIX=$HOSTNAME
else
    for NAME in azure gcp aws; do
        if [[ ${HOSTNAME} == ${NAME}-pod ]]; then
            export POSTFIX=${NAME}
        fi
    done
fi

if [ -z $POSTFIX ]; then
    if [ ! -f "/byoda/network-byoda.net/account-pod/pod-cert.pem" ]; then
        ACCOUNT_ID=$(ls /byoda)
        export POSTFIX=${ACCOUNT_ID:24:8}
    else
        echo "Assuming we are using the legacy directory structure"
    fi
fi

export ROOT_CA=/byoda/${POSTFIX}/network-$NETWORK/network-$NETWORK-root-ca-cert.pem
export PASSPHRASE=${PRIVATE_KEY_SECRET}

export ACCOUNT_CERT=/byoda/${POSTFIX}/network-byoda.net/account-pod/pod-cert.pem
export ACCOUNT_KEY=/byoda/${POSTFIX}/private/network-byoda.net-account-pod.key
if [ -f  ${ACCOUNT_CERT} ]; then
    export CERT_ACCOUNT_ID=$( \
            openssl x509 -in $ACCOUNT_CERT -noout -text | \
            grep accounts | \
            grep -v accounts-ca | \
            head -1 | \
            awk '{ print $16; } ' | \
            cut -f 1 -d . \
    )
    if [ "${CERT_ACCOUNT_ID}" != "${ACCOUNT_ID}" ]; then
        echo "WARNING: Account ID in cert (${CERT_ACCOUNT_ID}) does not match ACCOUNT_ID (${ACCOUNT_ID}) from byoda-settings.sh"
        export ACCOUNT_ID=${CERT_ACCOUNT_ID}
    fi
    export ACCOUNT_FQDN=${ACCOUNT_ID}.accounts.byoda.net
    export ACCOUNT_USERNAME_ORIGIN="environment"
    if [ -z "${ACCOUNT_USERNAME}" ]; then
        export ACCOUNT_USERNAME=$(echo $ACCOUNT_ID | cut -d '-' -f 1)
        export ACCOUNT_USERNAME_ORIGIN="account_id"
    fi
fi
export ACCOUNT_PASSWORD=${ACCOUNT_SECRET}

if [ -z "${CUSTOM_DOMAIN}" ]; then
    export HOME_PAGE="https://${ACCOUNT_ID}.accounts.byoda.net"
else
    export HOME_PAGE="https://${CUSTOM_DOMAIN}"
fi

echo "Setting:"
echo "ROOT CA cert                      : ${ROOT_CA}"
echo "Passphrase                        : ${PASSPHRASE}"
echo "Account ID                        : ${ACCOUNT_ID}"
echo "Account Username                  : ${ACCOUNT_USERNAME}"
echo "Account Password                  : ${ACCOUNT_PASSWORD}"
echo "Account FQDN                      : ${ACCOUNT_FQDN}"
echo "Account cert                      : ${ACCOUNT_CERT}"
echo "Account key                       : ${ACCOUNT_KEY}"
echo ""
echo "Custom domain                     : ${CUSTOM_DOMAIN}"
echo "Account page                      : ${HOME_PAGE}/"
echo "OpenAPI redoc                     : ${HOME_PAGE}/redoc"
echo "POD logs                          : ${HOME_PAGE}/logs/{pod[worker].log,angie-access.log,angie-error.log}"

# The byo.tube service
export SERVICE_BYOTUBE_ID=16384
export MEMBER_BYOTUBE_CERT=/byoda/${POSTFIX}/network-byoda.net/account-pod/service-${SERVICE_BYOTUBE_ID}/network-byoda.net-member-${SERVICE_BYOTUBE_ID}-cert.pem
export MEMBER_BYOTUBE_KEY=/byoda/${POSTFIX}/private/network-byoda.net-account-pod-member-${SERVICE_BYOTUBE_ID}.key
if [ -f  ${MEMBER_BYOTUBE_CERT} ]; then
    export MEMBER_BYOTUBE_ID=$( \
        openssl x509 -in $MEMBER_BYOTUBE_CERT -noout -text | \
        grep members | \
        grep -v members-ca | \
        head -1 | \
        awk '{ print $16; } ' | \
        cut -f 1 -d . \
    )
    export MEMBER_BYOTUBE_FQDN=${MEMBER_BYOTUBE_ID}.members-${SERVICE_BYOTUBE_ID}.byoda.net
fi

if [ "${ACCOUNT_USERNAME_ORIGIN}" == "environment" ]; then
    # if account username was set based on an environment variable, use that
    # for member username, otherwise take the first bits of the member_id
    export MEMBER_USERNAME=${ACCOUNT_USERNAME}
else
    export MEMBER_USERNAME=$(echo ${MEMBER_BYOTUBE_ID} | cut -d '-' -f 1)
fi

export MEMBER_ID=${MEMBER_BYOTUBE_ID}

echo ""
echo "BYOTube book service ID           : ${SERVICE_BYOTUBE_ID}"
echo "Member ID                         : ${MEMBER_BYOTUBE_ID}"
echo "Member FQDN                       : ${MEMBER_BYOTUBE_FQDN}"
echo "Member username                   : ${MEMBER_USERNAME}"
echo "Member cert                       : ${MEMBER_BYOTUBE_CERT}"
echo "Member key                        : ${MEMBER_BYOTUBE_KEY}"

