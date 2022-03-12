### Info on running pods on public clouds

Supported clouds: AWS, Azure and GCP.
Please review the features and requirements for the free services of the three clouds carefully to avoid unexpected costs.

AWS: https://aws.amazon.com/free
- 12 months free:
  - t2/t3.micro VM (1 CPU core, 1GB DRAM)
- always free:
   - CDN 1TB
Azure: https://azure.microsoft.com/en-us/free/
- credits: $200, one month expiration
- 12-months free
  - 1 x B1s VM (1 CPU core, 1GB DRAM)
  - 5GB blob
  - 15GB/m data out
- always free
  - 5GB/m data out
GCP: https://cloud.google.com/free/
- credits: $300, 90 days expiration
- always free (only in us-east1, us-west1, us-central1):
  - 1 x e2.micro VM (2 CPU cores, 1GB)
  - 5GB storage, 1GB data out (except China & Australia)


### Wipe the data of your pod
Wiping all the data of your pod from the pod VM is easy. We use service-based principals, so we don't have to specify credentials when we run the CLIs from the VM we run the pod on:
- Azure:
```
    az storage blob delete-batch -s byoda --account-name ${BUCKET_PREFIX}private --auth-mode login
```
- AWS:
```
    aws s3 rm s3://byoda-private/private --recursive
    aws s3 rm s3://byoda-private/network-byoda.net --recursive
```
- GCP:
```
    gcloud alpha storage rm --recursive gs://byoda-private/*
```
When you wipe all the data of your pod, make sure you also delete the file on the VM that tracks your account ID. By deleting the file, the docker-launch.sh script will generate a new one.
```
rm ~/.byoda-account_id
```
