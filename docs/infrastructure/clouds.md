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

Instructions on how to create a VM and storage account are available for:
- [AWS](https://github.com/StevenHessing/byoda-python/blob/master/docs/infrastructure/aws-vm-pod.md)
- [Azure](https://github.com/StevenHessing/byoda-python/blob/master/docs/infrastructure/azure-vm-pod.md)
- [GCP](https://github.com/StevenHessing/byoda-python/blob/master/docs/infrastructure/gcp-vm-pod.md)
