# Bring your own data & algorithms

## Intro
Byoda is a new and radically different social media platform:
- Your data is stored in your own data pod.
- Access to your data is controlled by a data contract and is enforced by your pod.
- You can select the algorithm(s) that generate your content feed for you.
- Anyone can develop apps and services on the platform.
- The code for the reference implementation of the various components is open source.

This repo hosts the reference implementation (in Python) of the Byoda directory server, a generic 'service' server and the data pod. For more information about Byoda, please go to the [web site](https://www.byoda.org/)

## Status
This is alpha-quality software. The only user interface available is curl. The byoda.net network is running, a proof-of-concept service 'Address Book' is up and running and you can install the data pod on a VM in AWS, Azure or GCP or on a server in your home.

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


## Basic info about the pod
- The logs of the pod are stored in /var/www/wwwroot/logs. This directory is volume-mounted in the pod. The certs and data files are stored under /byoda, which is also volume-mounted in the pod.<br>
- The 'directory server' for byoda.net creates a DNS record for each pod based on the ACCOUNT_ID of the pod. The ACCOUNT_ID is stored in the ~/.byoda-account_id file on your VM/server. The FQDN is '<ACCOUNT_ID>.accounts.byoda.net'.
- You can log into the web-interface of the pod using basic auth via the account FQDN. You will get a warning in your browser about a certificate signed by an unknown CA but you can ignore the warning. The username is the first 8 characters of your ACCOUNT_ID and the password is the string you've set for the ACCOUNT_SECRET variable in the docker-launch.sh script. You can use it to browse the OpenAPI docs ('/docs/' and '/redoc/') of your pod.

## Using the pod with the 'Address Book' service
The 'Address Book' service is a proof of concept on how a service in the BYODA network can operate. We can use _curl_ to our pod to join the address book service. Copy the [setenv.sh](https://github.com/StevenHessing/byoda-python/blob/master/docs/files/docker-lauch.sh) to the same directory as the docker-launch.sh script on your VM / server and source it:
```
source setenv.sh
```
Now we can use curl to get the list of services the pod has discovered in the network:
```
curl -s --cacert $ROOT_CA --cert $ACCOUNT_CERT --key $ACCOUNT_KEY --pass $PASSPHRASE \
    https://$ACCOUNT_FQDN/api/v1/pod/account | jq .
```

We can make our pod join the address book service:
```
curl -s -X POST --cacert $ROOT_CA --cert $ACCOUNT_CERT --key $ACCOUNT_KEY --pass $PASSPHRASE \
    https://$ACCOUNT_FQDN/api/v1/pod/member/service_id/$SERVICE_ADDR_ID/version/1 | jq .
```

We can confirm that our pod has joined the service with:
```
curl -s --cacert $ROOT_CA --cert $ACCOUNT_CERT --key $ACCOUNT_KEY --pass $PASSPHRASE \
    https://$ACCOUNT_FQDN/api/v1/pod/member/service_id/$SERVICE_ADDR_ID | jq .
```

And we can enter our data for the address book service after we fill in our data for the various fields to replace the placeholders between '<>':
```
curl -s -X POST -H 'content-type: application/json' \
    --cacert $ROOT_CA --cert $MEMBER_ADDR_CERT --key $MEMBER_ADDR_KEY --pass $PASSPHRASE \
    https://$MEMBER_ADDR_FQDN/api/v1/data/service-$SERVICE_ADDR_ID \
    --data '{"query": "mutation { mutate_person( given_name: \"<your given name>\", additional_names: \"\", family_name: \"<your family name>\", email: \"<your email address>\", homepage_url: \"<your homepage>\", avatar_url: \"\") { given_name additional_names family_name email homepage_url avatar_url } }" }'
```
To confirm that the pod now really has the data for your membership of the address book service:
```
curl -s -X POST -H 'content-type: application/json' \
    --cacert $ROOT_CA --cert $MEMBER_ADDR_CERT --key $MEMBER_ADDR_KEY --pass $PASSPHRASE \
    https://$MEMBER_ADDR_FQDN/api/v1/data/service-$SERVICE_ADDR_ID \
    --data '{"query": "query {person {given_name additional_names family_name email homepage_url avatar_url}}"}'
```
It will take a while for the address book service to retrieve your data from your pod and make it available from its search API. The address book service queries a pod every 10 seconds so the exact time depends on how many people have joined the service. In the meantime, you can call the search API to find the member_id of my email address: steven@byoda.org
```
curl -s --cacert $ROOT_CA --cert $MEMBER_ADDR_CERT --key $MEMBER_ADDR_KEY --pass $PASSPHRASE \
	https://service.service-$SERVICE_ADDR_ID.byoda.net/api/v1/service/search/steven@byoda.org  | jq .
```
Let's note the member_id from the output of the previous command and tell your pod to add me as your friend:
```
curl -s -X POST -H 'content-type: application/json' \
    --cacert $ROOT_CA --cert $MEMBER_ADDR_CERT --key $MEMBER_ADDR_KEY --pass $PASSPHRASE \
    https://$MEMBER_ADDR_FQDN/api/v1/data/service-$SERVICE_ADDR_ID \
    --data '{"query": "mutation { append_network_links( member_id: \"2eb0c68c-bb35-4595-930d-0c46e19a9e95\", relation: \"friend\", timestamp: \"2022-02-07T03:30:27.180230+00:00\") {  member_id relation timestamp } }" }' | jq .
```
Now let's see who your friends are in the membership for the address book service in your pod:
```
curl -s -X POST -H 'content-type: application/json' \
    --cacert $ROOT_CA --cert $MEMBER_ADDR_CERT --key $MEMBER_ADDR_KEY --pass $PASSPHRASE \
    https://$MEMBER_ADDR_FQDN/api/v1/data/service-$SERVICE_ADDR_ID \
    --data '{"query": "query {network_links {member_id relation timestamp}}" }' | jq .
```
We can also use JWTs. First, we acquire a JWT:
```
export ACCOUNT_JWT=$(curl -s --basic --cacert $ROOT_CA -u $ACCOUNT_USERNAME:$ACCOUNT_PASSWORD https://$ACCOUNT_FQDN/api/v1/pod/authtoken | jq -r .auth_token); echo $JWT
```
You can use the account JWT to call REST APIs on the POD, ie.:
```
curl -s --cacert $ROOT_CA -H "Authorization: bearer $ACCOUNT_JWT" https://$ACCOUNT_FQDN/api/v1/pod/account | jq .
```
If you need to call the GraphQL API, you need to have a member JWT:
```
export MEMBER_JWT=$(curl -s --basic --cacert $ROOT_CA -u $ACCOUNT_USERNAME:$ACCOUNT_PASSWORD https://$ACCOUNT_FQDN/api/v1/pod/authtoken/service_id/$SERVICE_ADDR_ID | jq -r .auth_token); echo $MEMBER_JWT
```
You can use the member JWT to query GraphQL API on the pod:
```
curl -s -X POST -H 'content-type: application/json' \
    --cacert $ROOT_CA -H "Authorization: bearer $MEMBER_JWT" \
    https://$MEMBER_ADDR_FQDN/api/v1/data/service-$SERVICE_ADDR_ID \
    --data '{"query": "query {person {given_name additional_names family_name email homepage_url avatar_url}}"}'
```

You can also use the member-JWT to call REST APIs against the server for the service:
```
curl -s --cacert $ROOT_CA --cert $MEMBER_ADDR_CERT --key $MEMBER_ADDR_KEY --pass $PASSPHRASE \
	https://service.service-$SERVICE_ADDR_ID.byoda.net/api/v1/service/search/steven@byoda.org  | jq .
```
## Hosting a service in the byoda.net network

Next to running your pod, everyone can develop their own service in the network. What you'll need to do is:
- Create a Service Contract in the form of a JSON Schema that models the data you want to store for the service in the data pod and who can access that data. The BYODA pod currently has limited support for complex data structures in the JSON-Schema so take the [service/addressbook.json](https://github.com/StevenHessing/byoda-python/blob/master/services/addressbook.json) as starting point. File an issue in Github as a feature request if you need support for a specific construct that is not currently supported.
- Get the Service Contract signed by the network
- On a host accessible from the Internet, make your modifications as needed for your service to the code under byoda-python/svcserver and run it as a service. The service server will automatically register with the network when it starts up. The directory server will create an FQDN 'service.service-<SERVICE_ID>.byoda.net with the public IP address of your host.
For more detailed instructions, please review the ['Creating a service' document](https://github.com/StevenHessing/byoda-python/blob/master/docs/infrastructure/create_a_service.md)

## TODO:
The main areas of development are:
- Enable web-browsers to call the APIs on the pod:
    - use TLS certs from Let's Encrypt
    - whitelisting CORS Origins for each service
- Implementing the 'network:+n' construct for the access permissions in the JSON Schema to allow people in your network to query your GraphQL APIs.
- Improve the support for complex data structures in the data contract.
- Add API to upload content to the public object storage

