# Instructions for creating a VM on GCP are to be completed

1. Create an account with [Google Cloud](https://console.cloud.google.com/)

2. Install uuid and jq
```
sudo apt-get install uuid jq
```

3. Install the [Google CLI tool 'gcloud'](https://cloud.google.com/sdk/docs/install)

4. Use the 'gcloud' command to log in, create a project and set the default region and zone
```
export PROJECT_ID=byodapod
gcloud init --no-browser
gcloud projects create ${PROJECT_ID} --name ${PROJECT_ID} --set-as-default
export REGION=us-central1
export ZONE="${REGION}-a"
gcloud config set compute/region ${REGION}
gcloud config set compute/zone ${ZONE}
```

5. Set a bunch of environment variables
```
export SSH_KEY=byoda-pod
export SSH_KEY_FILE="$HOME/.ssh/id_ed25519-${SSH_KEY}"
export SSH_PUB_KEY=$(cat ${SSH_KEY_FILE}.pub)
export VM_NAME=${PROJECT_ID}
export UUID=$(uuid)
export STORAGE_PREFIX="byoda${UUID:0:6}"
```

6. Generate SSH key and upload it
```
if [ ! -f ${SSH_KEY_FILE} ]; then
    ssh-keygen -t ed25519 -C ubuntu -f ${SSH_KEY_FILE}
fi
```

7. Create the storage buckets
```
gsutil mb -l ${REGION} -b on --pap enforced gs://${STORAGE_PREFIX}-private
gsutil mb -l ${REGION} -b on --pap inherited gs://${STORAGE_PREFIX}-public
```

8. Create a service account that allows the VM to access the storage buckets
```
gcloud iam service-accounts create --display-name ${VM_NAME}-storage ${VM_NAME}-storage
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${VM_NAME}-storage@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/storage.objectAdmin"

gsutil iam ch allUsers:legacyObjectReader gs://${STRAGE_PREFIX}-public

```
9. Create the VM
Let's create an Ubuntu 22.04 VM
```
MY_IP=$(curl -s ifconfig.co)
gcloud compute firewall-rules create allow-https \
    --allow TCP:443 \
    --priority 2000

gcloud compute firewall-rules create allow-http \
    --allow TCP:80 \
    --priority 2005

gcloud compute firewall-rules create allow-remote-ssh \
    --allow TCP:22 \
    --priority 2010 \
    --source-ranges="${MY_IP}/32"


VM_IP=$(gcloud compute instances create ${VM_NAME} \
    --image-family=ubuntu-minimal-2204-lts \
    --image-project ubuntu-os-cloud \
    --machine-type='e2-micro' \
    --no-public-ptr \
    --service-account="${VM_NAME}-storage@${PROJECT_ID}.iam.gserviceaccount.com" \
    --metadata="ssh-keys=ubuntu:${SSH_PUB_KEY}" \
    --scopes=logging-write,monitoring-write,trace,service-management,service-control,storage-full \
    --format json | jq -r '.[0].networkInterfaces[0].accessConfigs[0].natIP' \
); echo "VM IP: ${VM_IP}"

10. Validate you have remote access to the VM
All done, just confirm that you can ssh to the VM:
```
ssh -i ${SSH_KEY_FILE} ubuntu@${VM_IP}
```

If that works for you, you can continue with the remainder of the [tutorial](https://github.com/StevenHessing/byoda-python/blob/master/README.md).
