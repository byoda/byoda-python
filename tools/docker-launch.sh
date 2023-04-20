#!/bin/bash


export TAG=latest

if [ -d ".git" ]; then
    RESULT=$(grep byoda .git/config)
    if [ "$?" -eq "0" ]; then
        RESULT=$(git status | head -1 | grep 'branch master')
        if [ "$?" -eq "1" ]; then
            export TAG=dev
        fi
    fi
fi

WIPE_ALL=0
WIPE_MEMBER_DATA=0
KEEP_LOGS=0
args=$(getopt -l "help" -l "wipe-all" -l "wipe-member-data" -l "keep-logs" -l "tag" -o "t:" -- "$@")

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
        --wipe-member-data)
            WIPE_MEMBER_DATA=1
            ;;
        --keep-logs)
            KEEP_LOGS=1
            ;;
        -t|--tag)
            shift
            export TAG=$2
            ;;
        -h|--help)
            echo "$0: Launch the Byoda container"
            echo ""
            echo "Launches the Byoda container."
            echo ""
            echo "Usage: $0 [--help/-h] [--wipe-all] [--wipe-member-data] [--keep-logs]"
            echo ""
            echo "--help/-h             shows this helptext"
            echo "--wipe-all            wipe all of the data of the pod and creates a new account ID before launching te container"
            echo "--wipe-member-data    wipe all membership data of the pod before launching te container"
            echo "--keep-logs           do not delete the logs of the pod"
            echo "--tag [latest | dev ] use the dev or latest tag of the container"
            echo ""
            exit 0
            ;;
        *)
           ;;
    esac
    shift
done

###
### Pick up local settings for this byoda pod
###
echo "Loading settings from settings.sh"
source ~/byoda-settings.sh

if [[ "${TAG}" != "latest" && "${TAG}" != "dev" ]]; then
    echo "Invalid tag: ${TAG}"
    exit 1
fi

echo "Using Byoda container byoda-pod:${TAG}"

if [[ "${BUCKET_PREFIX}" == "changeme" || "${ACCOUNT_SECRET}" == "changeme" || "${PRIVATE_KEY_SECRET}" == "changeme" ]]; then
    echo "Set the BUCKET_PREFIX, ACCOUNT_SECRET and PRIVATE_KEY_SECRET variables in this script"
    exit 1
fi

if [[ -z "${BYODA_ROOT_DIR}" || "${BYODA_ROOT_DIR}" == "/" ]]; then
    echo "Set the BYODA_ROOT_DIR variable in this script"
    exit 1
fi

if [ ! -z "${CUSTOM_DOMAIN}" ]; then
    echo "Using custom domain: ${CUSTOM_DOMAIN}"
    PUBLICIP=$(curl -s https://ifconfig.me)
    DNSIP=$(host -t A ${CUSTOM_DOMAIN} | tail -1 | awk '{print $NF}')
    if [ "${DNSIP}" != "${PUBLICIP}" ]; then
        echo "Custom domain ${CUSTOM_DOMAIN} does not resolve to ${PUBLICIP}"
        echo "Please update the DNS record or unset the CUSTOM_DOMAIN variable"
        exit 1
    fi

    if [ -n "${LETSENCRYPT_DIRECTORY}" ]; then
        if [ ! -d "${LETSENCRYPT_DIRECTORY}" ]; then
            mkdir -p ${LETSENCRYPT_DIRECTORY}
        fi
        export LETSENCRYPT_VOLUME_MOUNT="-v ${LETSENCRYPT_DIRECTORY}:/etc/letsencrypt"
    fi
fi

export WWWROOT_VOLUME_MOUNT=
if [[ -n "${LOCAL_WWWROOT_DIRECTORY}" ]]; then
    echo "Volume mounting log directory: ${LOCAL_WWWROOT_DIRECTORY}"
    export WWWROOT_VOLUME_MOUNT="-v ${LOCAL_WWWROOT_DIRECTORY}:/var/www/wwwroot"
fi

if [[ "${KEEP_LOGS}" == "0" && -n "${LOCAL_WWWROOT_DIRECTORY}" ]]; then
    echo "Wiping logs: ${LOCAL_WWWROOT_DIRECTORY}/*.log"
    sudo rm -f ${LOCAL_WWWROOT_DIRECTORY}/logs/*.log
fi

export NGINXCONF_VOLUME_MOUNT=""
if [[ "${SHARED_WEBSERVER}" == "SHARED_WEBSERVER" ]]; then
    echo "Running on a shared webserver"
    export NGINXCONF_VOLUME_MOUNT="-v /etc/nginx/conf.d:/etc/nginx/conf.d -v /tmp:/tmp"
    if [[ ! -z "${CUSTOM_DOMAIN}" && "${MANAGE_CUSTOM_DOMAIN_CERT}" == "MANAGE_CUSTOM_DOMAIN_CERT" ]]; then
        echo "Using custom domain: ${CUSTOM_DOMAIN}"
        export PORT_MAPPINGS="-p 8000:8000 -p 80:80"
    else
        export PORT_MAPPINGS="-p 8000:8000"
    fi
else
    export PORT_MAPPINGS="-p 443:443 -p 444:444"

    if [[ ! -z "${CUSTOM_DOMAIN}" && "${MANAGE_CUSTOM_DOMAIN_CERT}" == "MANAGE_CUSTOM_DOMAIN_CERT" ]]; then
        echo "Using custom domain: ${CUSTOM_DOMAIN}"
        export PORT_MAPPINGS="-p 443:443 -p 444:444 -p 80:80"
    fi
fi

export AWS_CREDENTIALS=
if [ ! -z "${AWS_ACCESS_KEY_ID}" ]; then
    export AWS_CREDENTIALS="-e AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} -e AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}"
fi

export NETWORK="byoda.net"

# Set DAEMONIZE to FALSE to debug the podworker
export DAEMONIZE=TRUE

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
    echo "Wiping ${BYODA_ROOT_DIR}"
    sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR}/*
    sudo mkdir -p ${BYODA_ROOT_DIR}
    if [[ "${WIPE_ALL}" == "1" ]]; then
        which az > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            echo "azure-cli not found, please install it with 'curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash'"
            exit 1
        fi
        echo "Wiping all data of the pod"
        az storage blob delete-batch -s byoda --account-name ${BUCKET_PREFIX}private --auth-mode login
        if [ $? -ne 0 ]; then
            echo "Wiping Azure storage failed, you may have to run 'az login' first"
            exit 1
        fi
    elif [[ "${WIPE_MEMBER_DATA}" == "1" ]]; then
        echo "Wiping data and secrets for all memberships of the pod"
        az storage blob delete-batch -s byoda --account-name ${BUCKET_PREFIX}private --auth-mode login \
            --pattern private/network-${NETWORK}-account-pod-member-*.key
        az storage blob delete-batch --auth-mode login -s byoda --account-name ${BUCKET_PREFIX}private \
            --pattern private/network-${NETWORK}/account-pod/data/*
        az storage blob delete-batch --auth-mode login -s byoda --account-name ${BUCKET_PREFIX}private \
            --pattern network-${NETWORK}/account-pod/service-*/*
        az storage blob delete-batch --auth-mode login -s byoda --account-name ${BUCKET_PREFIX}private \
            --pattern network-${NETWORK}/services/*

        if [ $? -ne 0 ]; then
            echo "Wiping Azure storage failed, you may have to run 'az login' first"
            exit 1
        fi
    fi
elif [[ "${SYSTEM_MFCT}" == *"Google"* ]]; then
    export CLOUD=GCP
    echo "Running in cloud: ${CLOUD}"
    echo "Wiping ${BYODA_ROOT_DIR}"
    sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR}/*
    sudo mkdir -p ${BYODA_ROOT_DIR}
    if [[ "${WIPE_ALL}" == "1" ]]; then
        which gcloud > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            echo "gcloud-cli not found, please install it"
            exit 1
        fi
        echo "Wiping all data of the pod"
        gcloud alpha storage rm --recursive gs://${BUCKET_PREFIX}-private/*
    elif [[ "${WIPE_MEMBER_DATA}" == "1" ]]; then
        echo "Wiping data and secrets for all memberships of the pod"
        gcloud alpha storage rm --recursive gs://${BUCKET_PREFIX}-private/private/network-${NETWORK}-account-pod-member-*.key
        gcloud alpha storage rm --recursive gs://${BUCKET_PREFIX}-private/private/network-${NETWORK}/account-pod/data/*
        gcloud alpha storage rm --recursive gs://${BUCKET_PREFIX}-private/network-${NETWORK}/account-pod/service-*/*
        gcloud alpha storage rm --recursive gs://${BUCKET_PREFIX}-private/network-${NETWORK}/services/*

        if [ $? -ne 0 ]; then
            echo "Wiping GCP storage failed, you may have to run 'az login' first"
            exit 1
        fi
    fi
elif [[ "${SYSTEM_VERSION}" == *"amazon"* ]]; then
    export CLOUD=AWS
    echo "Running in cloud: ${CLOUD}"
    if [[ "${AWS_ACCESS_KEY_ID}" == "changeme" || "${AWS_SECRET_ACCESS_KEY}" == "changeme" ]]; then
        echo "Set the AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY variables in this script"
        exit 1
    fi
    echo "Wiping ${BYODA_ROOT_DIR}"
    sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR}/*
    sudo mkdir -p ${BYODA_ROOT_DIR}
    if [[ "${WIPE_ALL}" == "1" ]]; then
        which aws > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            echo "aws-cli-v2 not found, please install it"
            exit 1
        fi
        echo "Wiping all data of the pod"
        aws s3 rm -f s3://${BUCKET_PREFIX}-private/private --recursive
        aws s3 rm -f s3://${BUCKET_PREFIX}-private/network-${NETWORK} --recursive
    elif [[ "${WIPE_MEMBER_DATA}" == "1" ]]; then
        # echo "Wiping data and secrets for all memberships of the pod"
        # TODO
        echo "Wiping data and secrets for memberships not supported on AWS yet"
        exit 1
        aws s3 rm --recursive s3://${BUCKET_PREFIX}-private/private/network-${NETWORK}-account-pod-member-*.key
        aws s3 rm --recursive s3://${BUCKET_PREFIX}-private/private/network-${NETWORK}/account-pod/data/*
        aws s3 rm --recursive s3://${BUCKET_PREFIX}-private/network-${NETWORK}/account-pod/service-*/*
        aws s3 rm --recursive s3://${BUCKET_PREFIX}-private/network-${NETWORK}/services/*

        if [ $? -ne 0 ]; then
            echo "Wiping AWS storage failed, you may have to run 'aws login' first"
            exit 1
        fi
    fi
else
    export CLOUD=LOCAL
    echo "Not running in a public cloud"
    if [[ "${WIPE_ALL}" == "1" ]]; then
        echo "Wiping all data of the pod and creating a new account ID"
        sudo rm -rf -I --preserve-root=all ${BYODA_ROOT_DIR} 2>/dev/null
        sudo mkdir -p ${BYODA_ROOT_DIR}
        rm ${ACCOUNT_FILE}
    elif [[ "${WIPE_MEMBER_DATA}" == "1" ]]; then
        # echo "Wiping data and secrets for all memberships of the pod"
        # TODO
        rm -rf ${BYODA_ROOT_DIR}/private/network-${NETWORK}-account-pod-member-*.key
        rm -rf ${BYODA_ROOT_DIR}/private/network-${NETWORK}/account-pod/data/*
        rm -rf ${BYODA_ROOT_DIR}/network-${NETWORK}/account-pod/service-*/*
        rm -rf ${BYODA_ROOT_DIR}/network-${NETWORK}/services/*

        if [ $? -ne 0 ]; then
            echo "Wiping storage failed"
            exit 1
        fi
    fi
fi

if [[ "${WIPE_ALL}" == "1" ]]; then
    echo "Forcing creation of new account ID and deleting logs of the pod"
    rm ${ACCOUNT_FILE}
    sudo rm -f -I --preserve-root=all /var/www/wwwroot/logs/*
    sudo rm ${BYODA_ROOT_DIR}/*
    if [ ! -z "${LETSENCRYPT_DIRECTORY}" ]; then
        echo "Wiping Let's Encrypt directory: ${LETSENCRYPT_DIRECTORY}"
        sudo rm -rf -I --preserve-root=all ${LETSENCRYPT_DIRECTORY}/*
    fi
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

export LOGLEVEL=DEBUG
export BOOTSTRAP=BOOTSTRAP

sudo docker stop byoda 2>/dev/null
sudo docker rm byoda  2>/dev/null

if [[ "${CLOUD}" != "LOCAL" ]]; then
    # Wipe the cache directory
    sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR} 2>/dev/null
    sudo mkdir -p ${BYODA_ROOT_DIR}
fi

echo "Creating container for account_id ${ACCOUNT_ID}"
sudo docker pull byoda/byoda-pod:${TAG}

sudo docker run -d \
    --name byoda --restart=unless-stopped \
    -e "LOGLEVEL=${LOGLEVEL}" \
    ${PORT_MAPPINGS} \
    -e "WORKERS=1" \
    -e "CLOUD=${CLOUD}" \
    -e "BUCKET_PREFIX=${BUCKET_PREFIX}" \
    -e "PRIVATE_BUCKET=${PRIVATE_BUCKET}" \
    -e "PUBLIC_BUCKET=${PUBLIC_BUCKET}" \
    -e "NETWORK=${NETWORK}" \
    -e "ACCOUNT_ID=${ACCOUNT_ID}" \
    -e "ACCOUNT_SECRET=${ACCOUNT_SECRET}" \
    -e "PRIVATE_KEY_SECRET=${PRIVATE_KEY_SECRET}" \
    -e "BOOTSTRAP=BOOTSTRAP" \
    -e "ROOT_DIR=/byoda" \
    -e "TWITTER_USERNAME=${TWITTER_USERNAME}" \
    -e "TWITTER_API_KEY=${TWITTER_API_KEY}" \
    -e "TWITTER_KEY_SECRET=${TWITTER_KEY_SECRET}" \
    ${AWS_CREDENTIALS} \
    -e "CUSTOM_DOMAIN=${CUSTOM_DOMAIN}" \
    -e "MANAGE_CUSTOM_DOMAIN_CERT=${MANAGE_CUSTOM_DOMAIN_CERT}" \
    -e "SHARED_WEBSERVER=${SHARED_WEBSERVER}" \
    -v ${BYODA_ROOT_DIR}:/byoda \
    ${WWWROOT_VOLUME_MOUNT} \
    ${LETSENCRYPT_VOLUME_MOUNT} \
    ${NGINXCONF_VOLUME_MOUNT} \
    --ulimit nofile=65536:65536 \
    byoda/byoda-pod:${TAG}
