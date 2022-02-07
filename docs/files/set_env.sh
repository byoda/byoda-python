#!/usr/bin/bash

# Sets environment variables to facilitate using curl to tell the pod to do things

if [[ $_ == $0 ]]; then
    echo "$_: This script must be sourced instead of executed, e.g. 'source $_'"
    exit 1
fi

export ROOT_CA=/byoda/network-byoda.net/network-byoda.net-root-ca-cert.pem
export PASSPHRASE=$(grep PRIVATE_KEY_SECRET docker-launch.sh  | head -1 | cut -f 2 -d '=' | sed 's|"||g')

export ACCOUNT_CERT=/byoda/network-byoda.net/account-pod/pod-cert.pem
export ACCOUNT_KEY=/byoda/private/network-byoda.net-account-pod.key
export ACCOUNT_ID=$( \
        openssl x509 -in $ACCOUNT_CERT -noout -text | \
        grep accounts | \
        grep -v accounts-ca | \
        head -1 | \
        awk '{ print $16; } ' | \
        cut -f 1 -d . \
)
export ACCOUNT_FQDN=${ACCOUNT_ID}.accounts.byoda.net

# The address book service
export SERVICE_ADDR_ID=4294929430
export MEMBER_ADDR_CERT=/byoda/network-byoda.net/account-pod/service-${SERVICE_ADDR_ID}/network-byoda.net-member-${SERVICE_ADDR_ID}-cert.pem
export MEMBER_ADDR_KEY=/byoda/private/network-byoda.net-account-pod-member-${SERVICE_ADDR_ID}.key
if [ -f  $MEMBER_ADDR_CERT ]; then
    export MEMBER_ADDR_ID=$( \
        openssl x509 -in $MEMBER_ADDR_CERT -noout -text | \
        grep members | \
        grep -v members-ca | \
        head -1 | \
        awk '{ print $16; } ' | \
        cut -f 1 -d . \
    )
    export MEMBER_ADDR_FQDN=${MEMBER_ADDR_ID}.members-${SERVICE_ADDR_ID}.byoda.net
fi

