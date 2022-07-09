# Installing the BYODA pod on an Azure VM

This procedure assumes you have access to an existing linux system
1. Install the [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)
2. Install uuid and jq
```
sudo apt-get install uuid jq
```
3. Use the 'az login' command to log in
```
az login
```

4. Set some environment variables and an SSH key
```
export RG='byodapod'
export REGION=northcentralus
export SSH_KEY=byoda-pod
export SSH_KEY_FILE="$HOME/.ssh/id_rsa-${SSH_KEY}"
export VM_NAME=${RG}
export UUID=$(uuid)
export STORAGE_PREFIX="byoda${UUID:0:6}"
```

5. Generate SSH key and upload it
```
if [ ! -f ${SSH_KEY_FILE} ]; then
    ssh-keygen -t rsa -b 4096 -C ${SSH_KEY} -f ${SSH_KEY_FILE}
    az group create --name ${RG} --location ${REGION}
    az sshkey create --location ${REGION} --resource-group ${RG} --name byodassh --public-key "@${SSH_KEY_FILE}.pub"
fi
```

6. Create the storage accounts. MAke sure to write down the value for ${STORAGE_PREFIX} as you will need it when installing the pod on the VM you are creating with this procedure.
```
az storage account create \
    --name "${STORAGE_PREFIX}private" \
    --resource-group ${RG} \
    --location ${REGION} \
    --sku Standard_LRS \
    --allow-blob-public-access False \
    --min-tls-version TLS1_2
PRIVATE_SA_ID=$( \
    az storage account show \
        --name "${STORAGE_PREFIX}private" \
        --resource-group ${RG} \
    | jq -r .id)

az storage account create \
    --name "${STORAGE_PREFIX}public" \
    --resource-group ${RG} \
    --location ${REGION} \
    --sku Standard_LRS \
    --allow-blob-public-access True \
    --min-tls-version TLS1_2

PUBLIC_SA_ID=$( \
    az storage account show \
        --name "${STORAGE_PREFIX}public" \
        --resource-group ${RG} \
    | jq -r .id)

6. Create a network security group
We recommend restricting SSH access to the VM to the IP address you are currently using
```
MY_IP=$(curl ifconfig.co)
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
    --name https \
    --nsg-name byoda-nsg \
    --resource-group ${RG} \
    --priority 1010 \
    --access Allow \
    --direction Inbound \
    --protocol TCP \
    --destination-port-ranges 22 \
    --source-address-prefixes ${MY_IP}/32


7. Create the VM
```
IMAGE_URN=$(az vm image list --publisher Canonical -l "${REGION}" --sku "minimal-22_04-daily-lts-gen2" --all --architecture x64 | jq -r 'last| .urn'); echo Image: ${IMAGE_URN}
PUBLIC_IP=$( \
    az vm create \
        --resource-group ${RG} \
        --name ${VM_NAME} \
        --image ${IMAGE_URN} \
        --size Standard_B1s \
        --assign-identity [system] \
        --role contributor \
        --scope ${PRIVATE_SA_ID} \
        --ssh-key-name byodassh \
        --public-ip-address byoda-ip \
        --public-ip-sku Standard \
        --nsg byoda-nsg \
        --storage-sku Standard_LRS \
        --output json \
        --verbose \ | jq -r .publicIpAddress
)

VM_ID=$( \
    az vm show \
    --name ${VM_NAME} \
    --resource-group ${RG} \
    --output json | jq -r '.identity | .principalId' \
)


az role assignment create --assignee ${VM_ID} --role contributor --scope ${PUBLIC_SA_ID}

8.
All done, just validate you can ssh to the VM:
```
ssh -i ${SSH_KEY_FILE} azureuser@${PUBLIC_IP}
```
If that works for you, you can continue with the remainder of the tutorial.