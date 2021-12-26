# Running a pod on Azure

First of all, you need to to create an [Azure account](https://azure.microsoft.com/en-us/free/) if you do not already have one. Note that you solely are responsible for any and all costs incurred by following the below procedure. In addition to the cost for the VM, Azure will also charge fees for files stored in Azure storage accounts and for the I/O transactions used for these files. Additionally, Azure will charge fees for egress network traffic originating from the VM or the Azure storage account.

Install the [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli). After the installation, follow these instructions, which assume that you are using the Azure CLI on unix:

Pick a VM SKU. A 'Standard B1ls' or 'Standard B1' SKU should be sufficient to start.

Pick an [Azure region](https://azure.microsoft.com/en-us/global-infrastructure/geographies/) that you want to deploy to, probably close to where you live but you may also want to look at [pricing](https://azure.microsoft.com/en-us/pricing/details/virtual-machines/linux/). The name for the region for use with Azure CLI is different then those used in the Azure web pages. Use the following command to see the name to use with the Azure CLI in the last column of the table:
```
az login
az account list-locations -o table
```

First we set a set of variables for the deployment and create a work directory
```
VM_SKU=Standard_B1ls
PAYMENT_SCHEME='Regular'        # 'Spot' is not supported for B SKUs
REGION='westus2'
BYODA_DIR="${HOME}/.byoda"
mkdir -p ${BYODA_DIR}
chmod 700 ${BYODA_DIR}
MYIP=$(curl -s ifconfig.co)     # Used to restrict SSH access to the VM
```

See if we have already created resources previously that we now want to re-use
```
azure_bucket_file="${BYODA_DIR}/azure-bucket"
if [ -f "${azure_bucket_file}" ]; then
  BUCKETNAME=$(cat ${azure_bucket_file})
else
  BUCKETNAME=$(head /dev/urandom | tr -dc a-z0-9 | head -c 16 ; echo '')
  echo ${BUCKETNAME} > ${azure_bucket_file}
fi

azure_vm_file="${BYODA_DIR}/azure-vm"
if [ -f "${azure_vm_file}" ]; then
  VMNAME=$(cat ${azure_vm_file})
  echo "Does an Azure VM already exist with name ${VMNAME} ?"
else
  VMNAME=$(head /dev/urandom | tr -dc a-z0-9 | head -c 16 ; echo '')
  echo ${VMNAME} > ${azure_vm_file}
fi
```

Create an SSH key for accessing the VM:
```
test -f ${BYODA_DIR}/id_rsa-byoda-pod || ssh-keygen -t rsa -b 2048 -C 'byoda-pod' -f ${BYODA_DIR}/id_rsa-byoda-pod
chmod 600 ${BYODA_DIR}/id_rsa-byoda-pod
```

Now we start creating the Azure Resource Group and the Azure Proximity Placement Group:
```
az login  # follow the instructions to open a browser tab and complete the login procedure
az group show --name ${BUCKETNAME}  >/dev/null
if [ "$?" -ne "0" ]; then
    echo Creating Azure resource group ${BUCKETNAME}
    az group create --name ${BUCKETNAME} --location ${REGION} >/dev/null
fi
az ppg show -n ${BUCKETNAME} -g ${BUCKETNAME} >/dev/null
if [ "$?" -ne "0" ]; then
    echo Creating proximity placement group ${BUCKETNAME}
    az ppg create -n ${BUCKETNAME} -g ${BUCKETNAME} -l ${REGION} -t standard
fi
```

Create the storage bucket ('storage account' in Azure terminology)
```
az storage account show --name ${BUCKETNAME} >/dev/null
if [ "$?" -ne "0" ]; then
    echo Creating Azure Storage Account ${BUCKETNAME}
    az storage account create --name ${BUCKETNAME} -g ${BUCKETNAME} --location ${REGION} \
        --kind StorageV2 \
        --sku Standard_LRS \
        --assign-identity \
        --https-only true >/dev/null
fi
STORAGE_IDENTITY=$(az storage account show --name ${BUCKETNAME} -g ${BUCKETNAME} | jq -r .id)
```

Now we'll create the VM:
```
az vm availability-set show --name ${BUCKETNAME} -g ${BUCKETNAME}
if [ "$?" -ne "0" ]; then
    echo Creating Azure Availability Set ${BUCKETNAME}
    az vm availability-set create --name ${BUCKETNAME} -g ${BUCKETNAME} --location ${REGION} --ppg ${BUCKETNAME}
fi

az network nsg show -n ${BUCKETNAME} -g ${BUCKETNAME}  >/dev/null
if [ "$?" -ne "0" ]; then
    echo Creating Azure Network Security Group ${BUCKETNAME}
    az network nsg create -n ${BUCKETNAME} -g ${BUCKETNAME} -l ${REGION}
fi

az network nsg rule show -n https -g ${BUCKETNAME} --nsg-name ${BUCKETNAME}
if [ "$?" -ne "0" ]; then
    echo Creating NSG rule https
    az network nsg rule create -n https -g ${BUCKETNAME} --nsg-name ${BUCKETNAME} --priority 100 \
        --access Allow --direction Inbound --protocol Tcp \
        --source-address-prefixes Internet --source-port-ranges '*' \
        --destination-address-prefixes '*' --destination-port-ranges 443 >/dev/null
fi

az network nsg rule show -n ssh -g ${BUCKETNAME} --nsg-name ${BUCKETNAME}
if [ "$?" -ne "0" ]; then
    echo Creating NSG rule ssh
    az network nsg rule create -n ssh -g ${BUCKETNAME} --nsg-name ${BUCKETNAME} --priority 200 \
        --access Allow --direction Inbound --protocol Tcp \
        --source-address-prefixes ${MYIP}/32 --source-port-ranges '*' \
        --destination-address-prefixes '*' --destination-port-ranges 22 >/dev/null
fi

cat >/tmp/cloud-init.txt <<EOF
# cloud-config
runcmd:
  - apt-get install --yes apt-transport-https ca-certificates curl gnupg lsb-release
  - curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
  - echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
  - apt-get update
  - apt-get install --yes docker-ce docker-ce-cli containerd.io
EOF

az vm show --name ${VMNAME} -g ${BUCKETNAME}  >/dev/null
if [ "$?" -ne "0" ]; then
    echo Creating Azure VM $VMNAME
    PUBLICIP=$(az vm create --name ${VMNAME} -g ${BUCKETNAME} -l ${REGION} \
        --size ${VM_SKU} \
        --priority ${PAYMENT_SCHEME} \
        --availability-set ${BUCKETNAME} \
        --assign-identity \
        --enable-agent true \
        --authentication-type ssh \
        --ssh-key-values ${BYODA_DIR}/id_rsa-byoda-pod.pub \
        --admin-username ubuntu \
        --public-ip-address ${BUCKETNAME} \
        --public-ip-sku Standard \
        --vnet-name ${BUCKETNAME} \
        --vnet-address-prefix 172.16.128.0/27 \
        --subnet ${BUCKETNAME} \
        --subnet-address-prefix 172.16.128.0/27 \
        --image Canonical:0001-com-ubuntu-server-groovy:20_10:latest \
        --nsg ${BUCKETNAME} \
        --tags "bucket=${BUCKETNAME}" \
        --custom-data @/tmp/cloud-init.txt \
        | jq -r .publicIpAddress)
fi
```

Here we assign rights to the 'system-managed identity' of the VM for CRUD to the storage account
```
VM_IDENTITY=$(az vm show --name ${VMNAME} -g ${BUCKETNAME} | jq -r .identity.principalId)
 az role assignment create --role 'Storage Blob Data Contributor' --assignee ${VM_IDENTITY} --scope ${STORAGE_IDENTITY}
```

Naming for Azure Ubuntu images: https://github.com/Azure/azure-cli/issues/13320#issuecomment-649867249
Azure custom data: curl -H "Metadata:true" "http://169.254.169.254/metadata/instance/compute/customData?api-version=2019-02-01&&format=text" | base64 --decode
sudo cat /var/lib/waagent/ovf-env.xml | grep 'CustomData>' | sed -r 's/.*CustomData>([^<]+).*/\1/' | base64 --decode

According to Azure CLI, Azure Standard B1 skus do not support ephemeral OS or spot pricing
    PAYMENT_SCHEME=Spot
    --eviction-policy delete \
    --max-price -1 \


To delete the VM:
```
VMNAME=$(cat ${azure_vm_file})
DISK_ID=$(az vm show --name ${VMNAME} -g ${BUCKETNAME} | jq -r .storageProfile.osDisk.managedDisk.id)
NIC_ID=$(az vm show --name ${VMNAME} -g ${BUCKETNAME} | jq -r .networkProfile.networkInterfaces[0].id)
BUCKETNAME=$(cat ${azure_bucket_file})
az vm delete --yes --name ${VMNAME} -g ${BUCKETNAME}
az disk delete --yes --ids ${DISK_ID}
```
Need to make this working:
PUBLICIP=$( | jq -r .privateIpAddress)
ssh-keygen -f "/home/steven/.ssh/known_hosts" -R "${PUBLICIP}"
