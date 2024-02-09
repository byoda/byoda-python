#!/bin/bash

###
### Pick up local settings for this byoda pod
###
echo "Loading settings from byoda-settings.sh"

# Do not use $HOME or ~ as this script is run by cloud-init
# under the root account
if [ ! -d /home/azureuser ]; then
    export HOME_DIR="/home/ubuntu"
else
    # We are running on azure.byoda.me
    export HOME_DIR="/home/azureuser"
fi

if [ -f  ${HOME_DIR}/byoda-generic-settings.sh ]; then
    echo "Loading settings from ${HOME_DIR}/byoda-generic-settings.sh"
    source ${HOME_DIR}/byoda-generic-settings.sh
fi

if [ -f ${HOME_DIR}/byoda-settings.sh ]; then
    echo "Loading settings from ${HOME_DIR}/byoda-settings.sh"
    source ${HOME_DIR}/byoda-settings.sh
fi

if [ -f  ${HOME_DIR}/byoda-user-settings.sh ]; then
    echo "Loading settings from ${HOME_DIR}/byoda-user-settings.sh"
    source ${HOME_DIR}/byoda-user-settings.sh
fi


if [ -z "${TAG}" ]; then
    if [ -d ".git" ]; then
        RESULT=$(grep byoda .git/config)
        if [ "$?" -eq "0" ]; then
            RESULT=$(git status | head -1 | grep 'branch main')
            if [ "$?" -eq "1" ]; then
                export TAG=dev
            fi
        else
            export TAG=latest
        fi
    export TAG=latest
    fi
fi

WIPE_ALL=0
WIPE_MEMBER_DATA=0
WIPE_MEMBERSHIPS=0
KEEP_LOGS=0
args=$(getopt -l "help" -l "wipe-all" -l "wipe-member-data" -l "wipe-memberships" -l "keep-logs" -l "tag" -o "t:" -- "$@")

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
        --wipe-memberships)
            WIPE_MEMBERSHIPS=1
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
            echo "--wipe-memberships    wipe all membership data and secrets of the pod before launching te container"
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


if [[ "${TAG}" != "latest" && "${TAG}" != "dev" ]]; then
    echo "Invalid tag: ${TAG}"
    exit 1
fi

echo "Using Byoda container byoda-pod:${TAG}"

if [[ "${PRIVATE_BUCKET}" == "changeme" || "${RESTRICTED_BUCKET}" == "changeme" || "${PUBLIC_BUCKET}" == "changeme" ||"${ACCOUNT_SECRET}" == "changeme" || "${PRIVATE_KEY_SECRET}" == "changeme" ]]; then
    echo "Set the PRIVATE_BUCKET, RESTRICTED_BUCKET, PUBLIC_BUCKET, ACCOUNT_SECRET and PRIVATE_KEY_SECRET variables in this script"
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
            sudo mkdir -p ${LETSENCRYPT_DIRECTORY}
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
    if [ -z "${LOGDIR}" ]; then
        echo LOGDIR variable is not set
        exit 1
    fi
    echo "Wiping logs: ${LOGDIR}/*.log"
    sudo rm -f --preserve-root ${LOGDIR}/*.log

    if [ -z "${WEB_LOG_DIR}" ]; then
        echo WEB_LOG_DIR variable is not set
        exit 1
    fi
    echo "Wiping logs: ${WEB_LOG_DIR}/*.log"
    sudo rm -f --preserve-root ${WEB_LOG_DIR}/*.log
fi

export ANGIECONF_VOLUME_MOUNT=""
if [[ "${SHARED_WEBSERVER}" == "SHARED_WEBSERVER" ]]; then
    echo "Running on a shared webserver"
    export ANGIECONF_VOLUME_MOUNT="-v /etc/angie/conf.d:/etc/angie/conf.d"
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

# Set DAEMONIZE to FALSE to debug the pod_worker
export DAEMONIZE=TRUE

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

if [[ "${SYSTEM_MFCT}" == *"Microsoft Corporation"* ]]; then
    export CLOUD=Azure
    echo "Running in cloud: ${CLOUD}"
    if [[ "${WIPE_ALL}" == "1" ]]; then
        which az > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            echo "azure-cli not found, please install it with 'curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash'"
            exit 1
        fi

        if [ -z "${BYODA_ROOT_DIR}" ]; then
            echo BYODA_ROOT_DIR variable is not set
            exit 1
        fi
        echo "Wiping ${BYODA_ROOT_DIR}"
        sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR}/*

        if [ -z "${LOGDIR}" ]; then
            echo LOGDIR variable is not set
            exit 1
        fi
        echo "Wiping logs: ${LOGDIR}/*.log"
        sudo rm -f --preserve-root ${LOGDIR}/*.log

        if [ -z "${WEB_LOG_DIR}" ]; then
            echo WEB_LOG_DIR variable is not set
            exit 1
        fi
        echo "Wiping logs: ${WEB_LOG_DIR}/*.log"
        sudo rm -f --preserve-root ${WEB_LOG_DIR}/*.log

        STORAGE_ACCOUNT=$(echo ${PRIVATE_BUCKET} | cut -f 1 -d ':')
        echo "Wiping all data of the pod on storage account"
        az storage blob delete-batch -s byoda --account-name ${STORAGE_ACCOUNT} --auth-mode login
        if [ $? -ne 0 ]; then
            echo "Wiping the Azure storage account ${STORAGE_ACCOUNT} failed, you may have to run 'az login' first"
            exit 1
        fi
    elif [[ "${WIPE_MEMBERSHIPS}" == "1" ]]; then
        echo "Wiping data and secrets for all memberships of the pod"
        echo "Wiping ${BYODA_ROOT_DIR}"
        if [ -z "${BYODA_ROOT_DIR}" ]; then
            echo BYODA_ROOT_DIR variable is not set
            exit 1
        fi
        sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR}/*

        az storage blob delete-batch -s byoda --account-name ${PRIVATE_BUCKET} --auth-mode login \
           --pattern private/network-${NETWORK}-account-pod-member-*.key
        az storage blob delete-batch --auth-mode login -s byoda --account-name ${PRIVATE_BUCKET} \
            --pattern network-${NETWORK}/account-pod/service-*/*
        az storage blob delete-batch --auth-mode login -s byoda --account-name ${PRIVATE_BUCKET} \
            --pattern private/network-${NETWORK}/account-pod/data/*
        az storage blob delete-batch --auth-mode login -s byoda --account-name ${PRIVATE_BUCKET} \
            --pattern network-${NETWORK}/services/service-contract.json

        if [ $? -ne 0 ]; then
            echo "Wiping Azure storage failed, you may have to run 'az login' first"
            exit 1
        fi
    elif [[ "${WIPE_MEMBER_DATA}" == "1" ]]; then
        echo "Wiping data and service contracts for all memberships of the pod"
        echo "Wiping ${BYODA_ROOT_DIR}"
        if [ -z "${BYODA_ROOT_DIR}" ]; then
            echo BYODA_ROOT_DIR variable is not set
            exit 1
        fi
        sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR}/*

        az storage blob delete-batch --auth-mode login -s byoda --account-name ${PRIVATE_BUCKET} \
            --pattern private/network-${NETWORK}/account-pod/data/*
        az storage blob delete-batch --auth-mode login -s byoda --account-name ${PRIVATE_BUCKET} \
            --pattern network-${NETWORK}/account-pod/service-*/service-contract.json
        az storage blob delete-batch --auth-mode login -s byoda --account-name ${PRIVATE_BUCKET} \
            --pattern network-${NETWORK}/services/service-contract.json

        if [ $? -ne 0 ]; then
            echo "Wiping Azure storage failed, you may have to run 'az login' first"
            exit 1
        fi
    fi
elif [[ "${SYSTEM_MFCT}" == *"Google"* ]]; then
    export CLOUD=GCP
    echo "Running in cloud: ${CLOUD}"
    if [[ "${WIPE_ALL}" == "1" ]]; then
        echo "Wiping ${BYODA_ROOT_DIR}"
        if [ -z "${BYODA_ROOT_DIR}" ]; then
            echo BYODA_ROOT_DIR variable is not set
            exit 1
        fi
        sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR}/*

        which gcloud > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            echo "gcloud-cli not found, please install it"
            exit 1
        fi
        echo "Wiping all data of the pod"
        gcloud alpha storage rm --recursive gs://${PRIVATE_BUCKET}/*
        gcloud alpha storage rm --recursive gs://${RESTRICTED_BUCKET}/*
        gcloud alpha storage rm --recursive gs://${PUBLIC_BUCKET}/*
    elif [[ "${WIPE_MEMBERSHIPS}" == "1" ]]; then
        echo "Wiping ${BYODA_ROOT_DIR}"
        sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR}/*

        echo "Wiping data and secrets for all memberships of the pod"
        gcloud alpha storage rm --recursive gs://${PRIVATE_BUCKET}/private/network-${NETWORK}-account-pod-member-*.key
        gcloud alpha storage rm --recursive gs://${PRIVATE_BUCKET}/network-${NETWORK}/account-pod/service-*/*
        gcloud alpha storage rm --recursive gs://${PRIVATE_BUCKET}/private/network-${NETWORK}/account-pod/data/*
        gcloud alpha storage rm --recursive gs://${PRIVATE_BUCKET}/network-${NETWORK}/services/*

        if [ $? -ne 0 ]; then
            echo "Wiping GCP storage failed, you may have to run 'az login' first"
            exit 1
        fi
    elif [[ "${WIPE_MEMBER_DATA}" == "1" ]]; then
        echo "Wiping ${BYODA_ROOT_DIR}"
        sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR}/*

        echo "Wiping data and service contracts for all memberships of the pod"
        gcloud alpha storage rm --recursive gs://${PRIVATE_BUCKET}/private/network-${NETWORK}/account-pod/data/*
        gcloud alpha storage rm --recursive gs://${RESTRICTED_BUCKET}/network-${NETWORK}/account-pod/service-*/service-contract.json
        gcloud alpha storage rm --recursive gs://${PUBLIC_BUCKET}/network-${NETWORK}/services/*

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
    if [[ "${WIPE_ALL}" == "1" ]]; then
        echo "Wiping ${BYODA_ROOT_DIR}"
        if [ -z "${BYODA_ROOT_DIR}" ]; then
            echo BYODA_ROOT_DIR variable is not set
            exit 1
        fi
        sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR}/*

        which aws > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            echo "aws-cli-v2 not found, please install it"
            exit 1
        fi
        echo "Wiping all data of the pod"
        aws s3 rm -f s3://${PRIVATE_BUCKET}private/private --recursive
        aws s3 rm -f s3://${PRIVATE_BUCKET}private/network-${NETWORK} --recursive
    elif [[ "${WIPE_MEMBERSHIPS}" == "1" ]]; then
        echo "Wiping ${BYODA_ROOT_DIR}"
        sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR}/*

        # echo "Wiping data and secrets for all memberships of the pod"
        # TODO
        echo "Wiping data and secrets for memberships not supported on AWS yet"
        exit 1
        aws s3 rm --recursive s3://${PRIVATE_BUCKET}/private/network-${NETWORK}-account-pod-member-*.key
        aws s3 rm --recursive s3://${PRIVATE_BUCKET}/network-${NETWORK}/account-pod/service-*/*
        aws s3 rm --recursive s3://${PRIVATE_BUCKET}/private/network-${NETWORK}/account-pod/data/*
        aws s3 rm --recursive s3://${PRIVATE_BUCKET}/network-${NETWORK}/services/*

        if [ $? -ne 0 ]; then
            echo "Wiping AWS storage failed, you may have to run 'aws login' first"
            exit 1
        fi
    elif [[ "${WIPE_MEMBER_DATA}" == "1" ]]; then
        echo "Wiping ${BYODA_ROOT_DIR}"
        sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR}/*

        # echo "Wiping data and service contracts for all memberships of the pod"
        # TODO
        echo "Wiping data and secrets for memberships not supported on AWS yet"
        exit 1
        aws s3 rm --recursive s3://${PRIVATE_BUCKET}/private/network-${NETWORK}/account-pod/data/*
        aws s3 rm --recursive s3://${PRIVATE_BUCKET}/network-${NETWORK}/account-pod/service-*/service-contract.json
        aws s3 rm --recursive s3://${PRIVATE_BUCKET}/network-${NETWORK}/services/*

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
        if [ -z "${BYODA_ROOT_DIR}" ]; then
            echo BYODA_ROOT_DIR variable is not set
            exit 1
        fi
        sudo rm -rf -I --preserve-root=all ${BYODA_ROOT_DIR} 2>/dev/null
    elif [[ "${WIPE_MEMBERSHIPS}" == "1" ]]; then
        # echo "Wiping data and secrets for all memberships of the pod"
        # TODO
        if [ -z "${BYODA_ROOT_DIR}" ]; then
            echo BYODA_ROOT_DIR variable is not set
            exit 1
        fi
        rm -rf ${BYODA_ROOT_DIR}/private/network-${NETWORK}-account-pod-member-*.key
        rm -rf ${BYODA_ROOT_DIR}/network-${NETWORK}/account-pod/service-*/*
        rm -rf ${BYODA_ROOT_DIR}/private/network-${NETWORK}/account-pod/data/*
        rm -rf ${BYODA_ROOT_DIR}/network-${NETWORK}/services/*

        if [ $? -ne 0 ]; then
            echo "Wiping storage failed"
            exit 1
        fi
    elif [[ "${WIPE_MEMBER_DATA}" == "1" ]]; then
        if [ -z "${BYODA_ROOT_DIR}" ]; then
            echo BYODA_ROOT_DIR variable is not set
            exit 1
        fi
        # echo "Wiping data and service-contracts for all memberships of the pod"
        # TODO
        rm -rf --preserve-root ${BYODA_ROOT_DIR}/private/network-${NETWORK}/account-pod/data/*
        rm -rf --preserve-root ${BYODA_ROOT_DIR}/network-${NETWORK}/account-pod/service-*/service-contract.json
        rm -rf --preserve-root ${BYODA_ROOT_DIR}/network-${NETWORK}/services/*

        if [ $? -ne 0 ]; then
            echo "Wiping storage failed"
            exit 1
        fi
    fi
fi

if [[ "${WIPE_ALL}" == "1" ]]; then
    echo "Forcing creation of new account ID and deleting logs of the pod"
    if [ -z "${LOGDIR}" ]; then
        echo LOGDIR variable is not set
        exit 1
    fi
    sudo rm -f -I --preserve-root=all ${LOGDIR}/*

    if [ -z "${WEB_LOG_DIR}" ]; then
        echo WEB_LOG_DIR variable is not set
        exit 1
    fi
    sudo rm -f -I --preserve-root=all ${WEB_LOG_DIR}/*

    if [ -z "${BYODA_ROOT_DIR}" ]; then
        echo BYODA_ROOT_DIR variable is not set
        exit 1
    fi
    sudo rm ${BYODA_ROOT_DIR}/*
    if [ ! -z "${LETSENCRYPT_DIRECTORY}" ]; then
        echo "Wiping Let's Encrypt directory: ${LETSENCRYPT_DIRECTORY}"
        sudo rm -rf -I --preserve-root=all ${LETSENCRYPT_DIRECTORY}/*
    fi
fi

sudo mkdir -p ${BYODA_ROOT_DIR}

if [ -z "${LOGLEVEL}" ]; then
    export LOGLEVEL=INFO
fi

if [ -z "${WORKER_LOGLEVEL}" ]; then
    export WORKER_LOGLEVEL=INFO
fi

export LOGFILE=
export BOOTSTRAP=BOOTSTRAP

sudo docker stop byoda 2>/dev/null
sudo docker rm byoda  2>/dev/null

echo "Creating container for account_id ${ACCOUNT_ID}"

echo "DEBUG: ${DEBUG}"
echo "LOGLEVEL=${LOGLEVEL}"
echo "WORKER_LOGLEVEL: ${WORKER_LOGLEVEL}"
echo "LOGFILE: ${LOGFILE}"
echo "CLOUD: ${CLOUD}"
echo "PRIVATE_BUCKET: ${PRIVATE_BUCKET}"
echo "RESTRICTED_BUCKET: ${RESTRICTED_BUCKET}"
echo "PUBLIC_BUCKET: ${PUBLIC_BUCKET}"
echo "NETWORK: ${NETWORK}"
echo "ACCOUNT_ID: ${ACCOUNT_ID}"
echo "ACCOUNT_USERNAME: ${ACCOUNT_USERNAME}"
echo "ACCOUNT_SECRET: xxxxxxxx"
echo "PRIVATE_KEY_SECRET: xxxxxxxxx"
echo "BOOTSTRAP: ${BOOTSTRAP}"
echo "JOIN_SERVICE_IDS: ${JOIN_SERVICE_IDS}"
echo "ROOT_DIR: /byoda"
echo "YOUTUBE_CHANNEL: ${YOUTUBE_CHANNEL}"
echo "YOUTUBE_API_KEY: ${YOUTUBE_API_KEY}"
echo "YOUTUBE_IMPORT_SERVICE_ID: ${YOUTUBE_IMPORT_SERVICE_ID}"
echo "YOUTUBE_IMPORT_INTERVAL: ${YOUTUBE_IMPORT_INTERVAL}"
echo "CDN_APP_ID: ${CDN_APP_ID}"
echo "MODERATION_FQDN: ${MODERATION_FQDN}"
echo "MODERATION_APP_ID: ${MODERATION_APP_ID}"
echo "CUSTOM_DOMAIN: ${CUSTOM_DOMAIN}"
echo "MANAGE_CUSTOM_DOMAIN_CERT: ${MANAGE_CUSTOM_DOMAIN_CERT}"
echo "SHARED_WEBSERVER: ${SHARED_WEBSERVER}"
echo "TRACE_SERVER: ${TRACE_SERVER}"
echo "BYODA root directory: ${BYODA_ROOT_DIR}"
echo "LOGDIR: ${LOGDIR}"
echo "WEB_LOG_DIR: ${WEB_LOG_DIR}"
echo "PORT_MAPPINGS: ${PORT_MAPPINGS}"
echo "AWS_CREDENTIALS: xxxxxxxxxx"
echo "WWWROOT_VOLUME_MOUNT: ${WWWROOT_VOLUME_MOUNT}"
echo "LETSENCRYPT_VOLUME_MOUNT: ${LETSENCRYPT_VOLUME_MOUNT}"
echo "ANGIECONF_VOLUME_MOUNT: ${ANGIECONF_VOLUME_MOUNT}"

echo "Launching container"
sudo docker run -d --memory=800m \
    --name byoda --restart=unless-stopped \
    --pull always \
    --mount type=tmpfs,tmpfs-size=100M,destination=/tmp \
    -e "DEBUG=${DEBUG}" \
    -e "LOGLEVEL=${LOGLEVEL}" \
    -e "WORKER_LOGLEVEL=${WORKER_LOGLEVEL}" \
    -e "LOGFILE=${LOGFILE}" \
    ${PORT_MAPPINGS} \
    -e "WORKERS=1" \
    -e "LOGDIR=${LOGDIR}" \
    -e "WEB_LOG_DIR=${WEB_LOG_DIR}" \
    -e "BACKUP_INTERVAL=${BACKUP_INTERVAL}" \
    -e "CLOUD=${CLOUD}" \
    -e "PRIVATE_BUCKET=${PRIVATE_BUCKET}" \
    -e "RESTRICTED_BUCKET=${RESTRICTED_BUCKET}" \
    -e "PUBLIC_BUCKET=${PUBLIC_BUCKET}" \
    -e "NETWORK=${NETWORK}" \
    -e "ACCOUNT_ID=${ACCOUNT_ID}" \
    -e "ACCOUNT_USERNAME=${ACCOUNT_USERNAME}" \
    -e "ACCOUNT_SECRET=${ACCOUNT_SECRET}" \
    -e "PRIVATE_KEY_SECRET=${PRIVATE_KEY_SECRET}" \
    -e "BOOTSTRAP=BOOTSTRAP" \
    -e "JOIN_SERVICE_IDS=${JOIN_SERVICE_IDS}" \
    -e "ROOT_DIR=/byoda" \
    -e "YOUTUBE_CHANNEL=${YOUTUBE_CHANNEL}" \
    -e "YOUTUBE_API_KEY=${YOUTUBE_API_KEY}" \
    -e "YOUTUBE_IMPORT_SERVICE_ID=${YOUTUBE_IMPORT_SERVICE_ID}" \
    -e "YOUTUBE_IMPORT_INTERVAL=${YOUTUBE_IMPORT_INTERVAL}" \
    -e "CDN_APP_ID=${CDN_APP_ID}" \
    -e "MODERATION_FQDN=${MODERATION_FQDN}" \
    -e "MODERATION_APP_ID=${MODERATION_APP_ID}" \
    -e "TWITTER_USERNAME=${TWITTER_USERNAME}" \
    -e "TWITTER_API_KEY=${TWITTER_API_KEY}" \
    -e "TWITTER_KEY_SECRET=${TWITTER_KEY_SECRET}" \
    ${AWS_CREDENTIALS} \
    -e "CUSTOM_DOMAIN=${CUSTOM_DOMAIN}" \
    -e "MANAGE_CUSTOM_DOMAIN_CERT=${MANAGE_CUSTOM_DOMAIN_CERT}" \
    -e "SHARED_WEBSERVER=${SHARED_WEBSERVER}" \
    -e "TRACE_SERVER=${TRACE_SERVER}" \
    -v ${BYODA_ROOT_DIR}:/byoda \
    -v ${LOGDIR}:${LOGDIR} \
    -v ${WEB_LOG_DIR}:${WEB_LOG_DIR} \
    ${WWWROOT_VOLUME_MOUNT} \
    ${LETSENCRYPT_VOLUME_MOUNT} \
    ${ANGIECONF_VOLUME_MOUNT} \
    --ulimit nofile=65536:65536 \
    byoda/byoda-pod:${TAG}
