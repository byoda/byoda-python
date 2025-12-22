# Installing the BYODA pod on an Azure VM

The deployment steps below will create an Azure VM with a boot disk and a public IP address. You will need an existing Azure account to complete this procedure and you will be charged for the resources you create.

This procedure assumes you have access to an existing linux system

1. Install the [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)

2. Install uuid and jq

    ```bash
    sudo apt-get install uuid jq
    ```

3. Use the 'az login' command to log in

    ```bash
    az login
    ```

4. Set some environment variables and an SSH key

    ```bash
    export RG='byodapod'
    export REGION=northeurope
    export SSH_KEY=byoda-pod
    export SSH_KEY_FILE="$HOME/.ssh/id_rsa-${SSH_KEY}"
    export VM_NAME=${RG}
    export UUID=$(uuid -v 4)
    export STORAGE_ACCOUNT="byoda${UUID:0:6}"

    export RESTRICTED_CONTAINER="restricted-${UUID:24:12}"
    export PUBLIC_CONTAINER='public'
    export PRIVATE_CONTAINER='private'

    export PRIVATE_BUCKET="${STORAGE_NAME}:${PRIVATE_CONTAINER}"
    export RESTRICTED_BUCKET="${STORAGE_NAME}:${RESTRICTED_CONTAINER}"
    export PUBLIC_PUCKET="${STORAGE_NAME}:${PRIVATE_CONTAINER}"
    ```

5. Generate SSH key and upload it

    ```bash
    if [ ! -f ${SSH_KEY_FILE} ]; then
        ssh-keygen -t ed25519 -C ${SSH_KEY} -f ${SSH_KEY_FILE}
    fi
    az group create --name ${RG} --location ${REGION}
    az sshkey create --location ${REGION} --resource-group ${RG} --name byodapodssh --public-key "@${SSH_KEY_FILE}.pub"

    ```

6. Create the storage accounts. Make sure to write down the values for ${PRIVATE_BUCKET}, ${RESTRICTED_BUCKET}, and ${PUBLIC_BUCKET} as you will need it when installing the pod on the VM you are creating with this procedure.

    ```bash
    az storage account create \
        --name "${STORAGE_ACCOUNT}" \
        --resource-group ${RG} \
        --location ${REGION} \
        --sku Standard_LRS \
        --allow-blob-public-access True \
        --min-tls-version TLS1_2

    STORAGE_ACCOUNT_ID=$(az storage account show --name "${STORAGE_ACCOUNT}" --resource-group ${RG} | jq -r .id)

    az storage container create \
        --name ${PRIVATE_CONTAINER} \
        --account-name ${STORAGE_ACCOUNT} \
        --public-access off

    az storage container create \
        --name ${RESTRICTED_CONTAINER} \
        --account-name ${STORAGE_ACCOUNT} \
        --public-access blob

    az storage container create \
        --name ${PUBLIC_CONTAINER} \
        --account-name ${STORAGE_ACCOUNT} \
        --public-access blob
    ```

7. Create a network security group
We recommend restricting SSH access to the VM to the IP address you are currently using

    ```bash
    MY_IP=$(curl -s ifconfig.co); echo ${MY_IP}
    az network nsg create --name byoda-nsg --location ${REGION} --resource-group ${RG}
    az network nsg rule create \
        --name https \
        --nsg-name byoda-nsg \
        --resource-group ${RG} \
        --priority 1000 \
        --access Allow \
        --direction Inbound \
        --protocol TCP \
        --destination-port-ranges 443 \
        --source-address-prefixes Internet

    az network nsg rule create \
        --name https-alt \
        --nsg-name byoda-nsg \
        --resource-group ${RG} \
        --priority 1002 \
        --access Allow \
        --direction Inbound \
        --protocol TCP \
        --destination-port-ranges 444 \
        --source-address-prefixes Internet

    az network nsg rule create \
        --name http \
        --nsg-name byoda-nsg \
        --resource-group ${RG} \
        --priority 1005 \
        --access Allow \
        --direction Inbound \
        --protocol TCP \
        --destination-port-ranges 80 \
        --source-address-prefixes Internet

    az network nsg rule create \
        --name ssh \
        --nsg-name byoda-nsg \
        --resource-group ${RG} \
        --priority 1010 \
        --access Allow \
        --direction Inbound \
        --protocol TCP \
        --destination-port-ranges 22 \
        --source-address-prefixes ${MY_IP}/32
    ```

8. Create the VM
    Here we use an Ubuntu 24.04 minimal image. You can change the image as needed.
    
    ```bash
    IMAGE_URN=$(az vm image list --publisher Canonical -l "${REGION}" --sku "minimal-24_04-daily-lts-gen2" --all --architecture x64 | jq -r 'last| .urn'); echo Image: ${IMAGE_URN}
    PUBLIC_IP=$( \
        az vm create \
            --resource-group ${RG} \
            --location ${REGION} \
            --name ${VM_NAME} \
            --image ${IMAGE_URN} \
            --size Standard_B2ats_v2 \
            --public-ip-address byoda-ip \
            --public-ip-sku Standard \
            --nsg byoda-nsg \
            --storage-sku PREMIUM_LRS \
            --output json \
            --authentication-type ssh \
            --ssh-key-name byodapodssh \
            --admin-username ubuntu \
            --os-disk-name ${VM_NAME}-osdisk \
            --enable-agent true \
            --enable-hibernation false \
            --nic-delete-option Delete \
            --os-disk-delete-option Delete \
            --os-disk-size-gb 30 \
            --storage-sku Premium_LRS \
            --public-ip-address-allocation static \
            --public-ip-sku Standard \
            --accelerated-networking true \
            --accept-term \
            --verbose | jq -r .publicIpAddress \
    ); echo ${PUBLIC_IP}


    VM_ID=$( \
        az vm show \
        --name ${VM_NAME} \
        --resource-group ${RG} \
        --output json | jq -r '.identity | .principalId' \
    )

    az vm identity assign \
        -n ${VM_NAME} \
        -g ${RG} \
        --role "Storage Blob Data Contributor" \
        --scope ${STORAGE_ACCOUNT_ID}
    ```

9. Validation
    To specify the storage containers you created earlier when installing the BYODA pod, use the following environment variables:

    ```bash
    export PRIVATE_BUCKET="${STORAGE_ACCOUNT}:${PRIVATE_CONTAINER}"
    export RESTRICTED_BUCKET="${STORAGE_ACCOUNT}:${RESTRICTED_CONTAINER}"
    export PUBLIC_BUCKET="${STORAGE_ACCOUNT}:${PUBLIC_CONTAINER}"
    ```

    All done, just confirm that you can ssh to the VM:

    ```bash
    ssh -i ${SSH_KEY_FILE} ubuntu@${PUBLIC_IP}
    ```


    If that works for you, you can continue with the remainder of the [tutorial](https://github.com/byoda/byoda-python/blob/master/README.md).
