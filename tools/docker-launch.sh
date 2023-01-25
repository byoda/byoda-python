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

###
### Start of variables that you can configure
###

# Set to "IGNORE" when not using cloud storage
export BUCKET_PREFIX="changeme"
# Set the following two variables to long random strings
export ACCOUNT_SECRET="changeme"
export PRIVATE_KEY_SECRET="changeme"

# These variables need to be set only for pods on AWS:
export AWS_ACCESS_KEY_ID="changeme"
export AWS_SECRET_ACCESS_KEY="changeme"

# To impport your Twitter public tweets, sign up for Twitter Developer
# program at https://developer.twitter.com/ and set the following three
# environment variables (more instructions in
# https://github.com/StevenHessing/byoda-python/README.md)
export TWITTER_API_KEY=
export TWITTER_KEY_SECRET=
export TWITTER_USERNAME=

# To use a custom domain, follow the instructions in the section
# 'Certificates and browsers' in the README.md file.
export CUSTOM_DOMAIN=

# To install the pod on a (physical) server that already has nginx running,
# set the SHARED_WEBSERVER variable to 'SHARED_WEBSERVER'
export SHARED_WEBSERVER=

# To install the pod on a (physical) server that already has nginx running,
# and listens to port 80, and you want to use a CUSTOM_DOMAIN, unset the
# MANAGE_CUSTOM_DOMAIN_CERT variable
export MANAGE_CUSTOM_DOMAIN_CERT="MANAGE_CUSTOM_DOMAIN_CERT"

# If you are running on a shared webserver with a custom domain and can't
# make port 80 avaible then you'll have to generate the SSL cert yourself
# and store it in a directory that follows the Let's Encrypt directory
# lay-out and set the below variable to that directory
export LETSENCRYPT_DIRECTORY="/var/www/letsencrypt"

# With this option set to a directory, you can access the logs from the pod
# on the host VM or server as it will be volume mounted in the pod.
export LOCAL_WWWROOT_DIRECTORY=

# If you are not running in a cloud VM then you can change this to the
# directory where all data of the pod should be stored
export BYODA_ROOT_DIR=/byoda

# set DEBUG if you are interested in debug logs and troubleshooting the
# processes in the pod
export DEBUG=

###
### No changes needed below this line
###

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
            mkdir =p ${LETSENCRYPT_DIRECTORY}
        fi
        export LETSENCRYPT_VOLUME_MOUNT="-v ${LETSENCRYPT_DIRECTORY}:/etc/letsencrypt"
    fi
fi

export WWWROOT_VOLUME_MOUNT=
if [[ -n "${LOCAL_WWWROOT_DIRECTORY}" ]]; then
    echo "Volume mounting log directory: ${LOCAL_WWWROOT_DIRECTORY}"
    export WWWROOT_VOLUME_MOUNT="-v ${LOCAL_WWWROOT_DIRECTORY}:/var/www/wwwroot"
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
    fi
elif [[ "${SYSTEM_MFCT}" == *"Google"* ]]; then
    export CLOUD=GCP
    echo "Running in cloud: ${CLOUD}"
    echo "Wiping ${BYODA_ROOT_DIR}"
    sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR}/*
    sudo mkdir -p ${BYODA_ROOT_DIR}
    if [[ "${WIPE_ALL}" == "1" ]]; then
        echo "Wiping all data of the pod"
        gcloud alpha storage rm --recursive gs://${BUCKET_PREFIX}-private/*
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
        echo "Wiping all data of the pod"
        aws s3 rm -f s3://${BUCKET_PREFIX}-private/private --recursive
        aws s3 rm -f s3://${BUCKET_PREFIX}-private/network-byoda.net --recursive
    fi
else
    export CLOUD=LOCAL
    echo "Not running in a public cloud"
    if [[ "${WIPE_ALL}" == "1" ]]; then
        echo "Wiping all data of the pod and creating a new account ID"
        sudo rm -rf -I --preserve-root=all ${BYODA_ROOT_DIR} 2>/dev/null
        sudo mkdir -p ${BYODA_ROOT_DIR}
        rm ${ACCOUNT_FILE}
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

export LOGDIR=/var/www/wwwroot/logs
sudo mkdir -p ${LOGDIR}

sudo docker stop byoda 2>/dev/null
sudo docker rm byoda  2>/dev/null

if [[ "${CLOUD}" != "LOCAL" ]]; then
    # Wipe the cache directory
    sudo rm -rf --preserve-root=all ${BYODA_ROOT_DIR} 2>/dev/null
    sudo mkdir -p ${BYODA_ROOT_DIR}
fi

echo "Creating container for account_id ${ACCOUNT_ID}"
sudo docker pull byoda/byoda-pod:latest

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
    byoda/byoda-pod:latest
