# Bring your own data & algorithms

## Intro
Byoda is a mew and radically different social media platform:
- Your data is stored in your own data pod.
- Access to your data is controlled by a data contract and is enforced by your pod.
- You can select the algorithm(s) that generate your content feed for you.
- Anyone can develop apps and services on the platform.
- The code for the reference implementation of the various components is open source.

This repo hosts the reference implementation (in Python) of the Byoda directory server, a generic 'service' server and the data pod. For more information about Byoda, please go to the [web site](https://www.byoda.org/)

## Status
This is alpha-quality software. The only user interface available is curl. The byoda.net network is running, the Address Book proof-of-concept service is running and you can install the data pod on a VM in AWS, Azure or GCP or on a server in your home. Work is yet to be done to enable web-browsers to call the APIs on the pod and to improve the support for complex data structures in the data contract.

## Getting started with the data pod
There are two ways to install the pod:
1. Use a public cloud like Amazon Web Services, Microsoft Azure or Google Cloud.
    - Create a VM with a public IP address, The VM should have at least 1GB of memory and 8GB of disk space.
    - Create two buckets (AWS/GCP) or storage accounts (Azure).
        - Pick a random string (ie. 'mybyoda') and the name of the storage accounts must then be that string appended with '-private' and '-public', (ie.: 'mybyoda-private' and 'mybyoda-public').
        - Disable public access to the buckets/storage-accounts. If the cloud has the option available, specify uniform access for all objects.
        - Use 'managed-identity'-based access to grant the VM full access to the buckets/storage-accounts.
    - The HTTPS port for the public IP must be accessible from the Internet and the SSH port must be reachable from your home IP address (or any other IP address you trust).
    - Running the VM, its public IP address and the storage may incur costs, unless you manage to stay within the limits of the free services offered by:
        - [AWS](https://aws.amazon.com/free), consider using the t2.micro SKU for the VM.
        - [Azure](https://azure.microsoft.com/en-us/free/), consider using the B1s SKU for the VM.
        - [GCP](https://cloud.google.com/free/), consider using the e2-micro SKU for the VM.
2. Install the pod as a docker container in a server in your home.
    - Port 443 on your server must be available for the pod to use
    - Port 443 must be accessible from the Internet.
    - Carefully consider the security implementations on enabling port forwarding on your broadband router and whether this is the right setup for you.

To launch the pod:
- Log in to your VM or server
- Copy the [docker-launch.sh script](https://github.com/StevenHessing/byoda-python/blob/master/docs/files/docker-lauch.sh) to the VM
- Edit the docker-launch.sh script and modify the following variables at the top of the script
  - BUCKET_PREFIX: in the above example, that would be 'mybyoda'
  - ACCOUNT_SECRET: set it to a long random string; it can be used as credential for browsing your pod
  - PRIVATE_KEY_SECRET: set it to a long random string; it will be used for the private keys that the pod will create
- Install the docker, uuid and jq packages and launch the pod

```
sudo apt update && apt-get install -y docker uuid jd
chmod 755 docker-launch.sh
./docker-launch.sh
```

**Congratulations, you now have a running pod that is member of the byoda.net network!** <br>
The logs of the pod are stored in /var/www/wwwroot/logs. This directory is volume-mounted in the pod. The certs and data files are stored under /byoda, which is also volume-mounted in the pod.<br>
The 'directory server' for byoda.net creates a DNS record for each pod based on the ACCOUNT_ID of the pod, which is stored in the ~/.byoda-account_id file on your VM/server. The FQDN is '<ACCOUNT_ID>.accounts.byoda.net'. You can log to the web-interface of the pod in using basic auth to the pod using the account FQDN. You can use it to browse the OpenAPI docs ('/docs/' and '/redoc/') of your pod. The username is the first 8 characters of your ACCOUNT_ID and the password is the string you've set for the ACCOUNT_SECRET variable in the docker-launch.sh script.<br>

## Using the pod with the 'Address Book' service
The 'Address Book' service is a proof of concept on how a service in the BYODA network can operate. We can use _curl_ to our pod to join the service:
```
