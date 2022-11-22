#!/usr/bin/bash

# Sets environment variables to facilitate using curl to tell the pod to do things

# maintainer : Steven Hessing <steven@byoda.org>
# copyright  : Copyright 2021, 2022
# license    : GPLv3

if [[ $_ == $0 ]]; then
    echo "$_: This script must be sourced instead of executed, e.g. 'source $_'"
    exit 1
fi

export PYTHONPATH=$PYTHONPATH:$(pwd):~/byoda-python:~/src/byoda-python:/root/byoda-python:/root/src/byoda-python
export NETWORK="byoda.net"

export ROOT_CA=/byoda/network-$NETWORK/network-$NETWORK-root-ca-cert.pem
export PASSPHRASE=$(grep PRIVATE_KEY_SECRET ~/docker-launch.sh  | head -1 | cut -f 2 -d '=' | sed 's|"||g')

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
export ACCOUNT_USERNAME=$(echo $ACCOUNT_ID | cut -d '-' -f 1)
export ACCOUNT_PASSWORD=$(grep ACCOUNT_SECRET ~/docker-launch.sh | head -1 | cut -f 2 -d '=' | sed 's|"||g')

echo "Setting:"
echo "ROOT CA cert                      : $ROOT_CA"
echo "Passphrase                        : $PASSPHRASE"
echo "Account ID                        : $ACCOUNT_ID"
echo "Account Username                  : $ACCOUNT_USERNAME"
echo "Account Password                  : $ACCOUNT_PASSWORD"
echo "Account FQDN                      : $ACCOUNT_FQDN"
echo "Account cert                      : $ACCOUNT_CERT"
echo "Account key                       : $ACCOUNT_KEY"
echo ""
echo "Account page                      : https://$ACCOUNT_ID.accounts.byoda.net/"
echo "OpenAPI redoc                     : https://$ACCOUNT_ID.accounts.byoda.net/redoc"
echo "POD logs                          : https://$ACCOUNT_ID.accounts.byoda.net/logs/{pod[worker].log,nginx-access.log,nginx-error.log}"

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
export MEMBER_USERNAME=$(echo $MEMBER_ADDR_ID | cut -d '-' -f 1)
export MEMBER_ID=$MEMBER_ADDR_ID

echo ""
echo "Address book service ID           : $SERVICE_ADDR_ID"
echo "Member ID                         : $MEMBER_ADDR_ID"
echo "Member FQDN                       : $MEMBER_ADDR_FQDN"
echo "Member username                   : $MEMBER_USERNAME"
echo "Member cert                       : $MEMBER_ADDR_CERT"
echo "Member key                        : $MEMBER_ADDR_KEY"
echo ""
echo "GraphQL API endpoint for pods     : https://$MEMBER_ADDR_ID.members-$SERVICE_ADDR_ID.byoda.net/api/v1/data/service-$SERVICE_ADDR_ID"
echo "GraphQL API endpoint for browsers : https://proxy.byoda.net/$SERVICE_ADDR_ID/$MEMBER_ADDR_ID/api/v1/data/service-$SERVICE_ADDR_ID"