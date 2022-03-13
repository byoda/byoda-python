#!/bin/bash

WIPE_ALL=0

args=$(getopt -l "help" -l "wipe-all" -o "" -- "$@")

eval set -- "$args"

while [ $# -ge 1 ]; do
    case "$1" in
        --)
            # No more options left.
            shift
            break
            ;;
        --wipe-all)
            WIPE_ALL=1
            ;;
        -h|--help)
            echo "$0: Launch the Byoda container"
            echo ""
            echo "Launches the Byoda container."
            echo ""
            echo "Usage: $0 [--help/-h] [--wipe-all]"
            echo ""
            echo "--help/-h     shows this helptext"
            echo "--wipe-all    wipe all of the data of the pod and creates a new account ID before launching te container"
            echo ""
            return 0
            ;;
        *)
           ;;
    esac
    shift
done

# Set to "IGNORE" when not using cloud storage
export BUCKET_PREFIX="changeme"
# Set the following two variables to long random strings
export ACCOUNT_SECRET="changeme"
export PRIVATE_KEY_SECRET="changeme"

if [[ "${BUCKET_PREFIX}" == "changeme" || "${ACCOUNT_SECRET}" == "changeme" || "${PRIVATE_KEY_SECRET}" == "changeme" ]]; then
    echo "Set the BUCKET_PREFIX, ACCOUNT_SECRET and PRIVATE_KEY_SECRET variables in this script"
    exit 1
fi

ACCOUNT_FILE=~/.byoda-account_id

DOCKER=$(which docker)

if [ $? -ne 0 ]; then
    echo "Docker binary not found, please install it"
    exit 1
fi

SYSTEM_MFCT=$(sudo dmidecode -t system | grep Manufacturer)
SYSTEM_VERSION=$(sudo dmidecode -t system | grep Version)
echo "System info:"
echo "    ${SYSTEM_MFCT}"
echo "    ${SYSTEM_VERSION}"

PRIVATE_BUCKET="${BUCKET_PREFIX}-private"
PUBLIC_BUCKET="${BUCKET_PREFIX}-public"

if [[ "${SYSTEM_MFCT}" == *"Microsoft Corporation"* ]]; then
    export CLOUD=Azure
    echo "Running in cloud: ${CLOUD}"
    # In Azure we don't have the '-' between prefix and private/public
    PRIVATE_BUCKET=${BUCKET_PREFIX}private
    PUBLIC_BUCKET=${BUCKET_PREFIX}public
    if [[ "${WIPE_ALL}" == "1" ]]; then
        echo "Wiping all data of the pod"
        az storage blob delete-batch -s byoda --account-name ${BUCKET_PREFIX}private --auth-mode login
    fi
elif [[ "${SYSTEM_MFCT}" == *"Google"* ]]; then
    export CLOUD=GCP
    echo "Running in cloud: ${CLOUD}"
    if [[ "${WIPE_ALL}" == "1" ]]; then
        echo "Wiping all data of the pod"
        gcloud alpha storage rm --recursive gs://${BUCKET_PREFIX}-private/*
    fi
elif [[ "${SYSTEM_VERSION}" == *"amazon"* ]]; then
    export CLOUD=AWS
    echo "Running in cloud: ${CLOUD}"
    if [[ "${WIPE_ALL}" == "1" ]]; then
        echo "Wiping all data of the pod"
        aws s3 rm s3://${BUCKET_PREFIX}-private/private --recursive
        aws s3 rm s3://${BUCKET_PREFIX}-private/network-byoda.net --recursive
    fi
else
    export CLOUD=LOCAL
    echo "Not runing in a public cloud"
    if [[ "${WIPE_ALL}" == "1" ]]; then
        echo "Wiping all data of the pod and creating a new account ID"
        sudo rm -rf ${ROOT_DIR} 2>/dev/null
        sudo mkdir -p ${ROOT_DIR}
        rm ${ACCOUNT_FILE}
    fi
fi

if [[ "${WIPE_ALL}" == "1" ]]; then
    echo "Forcing creation of new account ID and deleting logs of the pod"
    rm ${ACCOUNT_FILE}
    sudo rm /var/www/wwwroot/logs/*
fi

if [ -f "${ACCOUNT_FILE}" ]; then
    ACCOUNT_ID=$(cat ${ACCOUNT_FILE})
    echo "Reading account_id from ${ACCOUNT_FILE}: ${ACCOUNT_ID}"
else
    ACCOUNT_ID=$(uuid -v 4)
    if [ $? -ne 0 ]; then
        echo "Failed to run 'uuid', please install it"
        exit 1
    fi
    echo $ACCOUNT_ID >${ACCOUNT_FILE}
    echo "Writing account_id to ${ACCOUNT_FILE}: ${ACCOUNT_ID}"
fi

export ROOT_DIR=/byoda
export LOGLEVEL=DEBUG
export BOOTSTRAP=BOOTSTRAP

export LOGDIR=/var/www/wwwroot/logs
sudo mkdir -p ${LOGDIR}

sudo docker stop byoda 2>/dev/null
sudo docker rm byoda  2>/dev/null

if [[ "${CLOUD}" != "LOCAL" ]]; then
    # Wipe the cache directory
    sudo rm -rf ${ROOT_DIR} 2>/dev/null
    sudo mkdir -p ${ROOT_DIR}
fi

echo "Creating container for account_id ${ACCOUNT_ID}"
docker pull byoda/byoda-pod:latest
sudo docker run -d \
    --name byoda \
    -p 443:443 -p 444:444 -p 80:80 \
    -e "CLOUD=${CLOUD}" \
    -e "BUCKET_PREFIX=${BUCKET_PREFIX}" \
    -e "PRIVATE_BUCKET=${PRIVATE_BUCKET}" \
    -e "PUBLIC_BUCKET=${PUBLIC_BUCKET}" \
    -e "NETWORK=byoda.net" \
    -e "ACCOUNT_ID=${ACCOUNT_ID}" \
    -e "ACCOUNT_SECRET=${ACCOUNT_SECRET}" \
    -e "LOGLEVEL=${LOGLEVEL}" \
    -e "PRIVATE_KEY_SECRET=${PRIVATE_KEY_SECRET}" \
    -e "BOOTSTRAP=BOOTSTRAP" \
    -e "ROOT_DIR=${ROOT_DIR}" \
    -v ${ROOT_DIR}:${ROOT_DIR} \
    -v ${LOGDIR}:${LOGDIR} \
    byoda/byoda-pod:latest
