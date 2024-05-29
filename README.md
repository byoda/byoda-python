# Bring your own data & algorithms

## Intro

Byoda is a personal data store with features enabling new and radically different social media services:

- Your data is stored in your own personal data store (or 'pod').
- Access to your data is controlled by a __data contract__ and is enforced by a __data firewall__.
- You can select the algorithms that generate your content feed for you.
- You can store your unique content in your own pod and monetize it.
- Anyone can develop apps and services on the platform.
- The code for the reference implementation of the various components is open source.

This repo hosts the reference implementation (in Python) of the Byoda directory server, a generic 'service' server, a moderation server, and the data pod. For more information about Byoda, please go to the [web site](https://www.byoda.org/)

## Status

This is alpha-quality software. The only user interface available today is curl and a tool to call APIs to manage data. If you don't know what curl is, this software is probably not yet mature enough for you. The byoda.net network is running, a proof-of-concept service 'Address Book' is up and running and you can install the data pod on a VM in AWS, Azure or GCP or on a server in your home.

## Getting started with the data pod

There are two ways to install the pod:

1. Use a public cloud like Amazon Web Services, Microsoft Azure or Google Cloud.
    - Create an account with the cloud provider of choice
    - Create a VM with a public IP address, The VM should have at least 1GB of memory and 8GB of disk space.
    - Create three buckets (AWS/GCP) or, for Azure a storage account with three containers.
        - For AWS/GCP: Pick a random string (ie. 'mybyoda') and the name of the storage accounts must then be that string appended with '-private', '-public' and '-restricted-[random-string-of-12-characters]', (ie.: 'mybyoda-private', 'mybyoda-public', and 'mybyoda-restricted-abcdefghij'). The bucket names have to be globally unique so you may have to try different strings.
        - For Azure, pick a random string and create a storage account with that string.
        - Disable public access to the '-private' bucket or storage-account container. If the cloud has the option available, specify uniform access for all objects.
    - Follow the cloud-specific instructions for creating the VM to run the pod on
        - [Azure](https://github.com/byoda/byoda-python/blob/master/docs/infrastructure/azure-vm-pod.md)
        - [AWS](https://github.com/byoda/byoda-python/blob/master/docs/infrastructure/aws-vm-pod.md)
        - [GCP](https://github.com/byoda/byoda-python/blob/master/docs/infrastructure/gcp-vm-pod.md)
    - Ports 80, 443 and 444 for the public IP must be accessible from the Internet and the SSH port must be reachable from your home IP address (or any other IP address you trust).
    - Running the VM, its public IP address and the storage may incur costs, unless you manage to stay within the limits of the free services offered by:
        - [Azure](https://azure.microsoft.com/en-us/free/), consider using the B1s SKU for the VM.
        - [AWS](https://aws.amazon.com/free), consider using the t2.micro SKU for the VM.
        - [GCP](https://cloud.google.com/free/), consider using the e2-micro SKU for the VM.
2. Install the pod as a docker container in a server in your home.
    - TCP ports 80, 443, and port 444 on your server must be available for the pod to use and must be accessible from the Internet
    - Carefully consider the security implications of enabling port forwarding on your broadband router and whether this is the right setup for you.
    - Detailed instructions are available for running the pod on your [server](https://github.com/byoda/byoda-python/blob/master/docs/infrastructure/server-pod.md)

If you manage a DNS domain then you have the option of using a _custom domain_. You need to create a dns A record in your domain that points to the public IP of your pod. You can then update the _CUSTOM DOMAIN_ variable in the ```~/byoda-settings.sh``` script to the domain name you created. If you do not have a custom domain then you can still use the pod but you'll have to use the proxy at proxy.byoda.net to access your pod. See the section on _Access security_ for more information.

To launch the pod:

- Log in to your VM or server.
- Install some tools, make sure there is some swap space for the kernel, and clone the [byoda repository](https://github.com/byoda/byoda-python.git)

```bash
sudo apt update && sudo apt-get install -y docker.io uuid jq git vim python3-pip bind9-host sqlite3 libnng1

git clone https://github.com/byoda/byoda-python.git
```

If (and only if) you created a _new_ VM in a public cloud for your pod then create a swap file:

```bash
SWAP=$(free | grep -i swap | awk '{ print $4;}')
if [[ "${SWAP}" == "0" && ! -f /swapfile ]]; then
    sudo fallocate -l 1024m /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile && echo "/swapfile swap swap defaults 0 0" | sudo tee -a /etc/fstab
fi
```

- Copy and edit the tools/byoda-settings.sh script and modify the variables in the script
  - PRIVATE_BUCKET
  - RESTRICTED_BUCKET
  - PUBLIC_BUCKET
  - ACCOUNT_SECRET: set it to a long random string; it can be used as credential for browsing your pod
  - PRIVATE_KEY_SECRET: set it to a long random string; it will be used for the private keys that the pod will create
  - if you deployed a VM on AWS, also edit the variables:
    - AWS_ACCESS_KEY_ID
    - AWS_SECRET_ACCESS_KEY
  - Make sure to store the values for ACCOUNT_SECRET and PRIVATE_KEY_SECRET to a secure place as without them, you have no way to recover the data in your pod if things go haywire.
  - You can ignore the other variables that can be set in this file. They'll be discussed in other sections of the documentation

```bash
sudo mkdir /byoda 2>/dev/null
cd byoda-python
cp tools/docker-launch.sh tools/byoda-settings.sh ~
vi ~/byoda-settings.sh
```

For GCP/AWS, the storage settings in ~/byoda-settings.sh should look something like:

```bash
export PRIVATE_BUCKET="mybyoda-private"
export RESTRICTED_BUCKET="mybyoda-restricted-abcdefghij"
export PUBLIC_BUCKET="mybyoda-public"
```

For Azure, the storage settings in ~/byoda-settings.sh should look something like:

```bash
export PRIVATE_BUCKET="mybyodaprivate:byoda"
export RESTRICTED_BUCKET="mybyodaprivate:restricted-abcdef"
export PUBLIC_BUCKET="mybyodaprivate:public"

```

- Now run the ```tools/set_env.sh``` script and note the value for _Account ID_ in the output, then execute the docker-launch.sh script.

```bash
source tools/set_env.sh
~/docker-launch.sh
```

**Congratulations, you now have a running pod that is a member of the byoda.net network!**

## Basic info about the pod

- The logs of the pod are stored in /var/log/byoda. The ```docker-launch.sh``` script uses docker-compose.yaml to bind this directory for the pod. The certs and data files are stored in the cloud or locally on your server. In either case, they are (also) availble under /byoda, which is also bind-mounted in the pod by the ```docker-launch.sh``` script.
- The 'directory server' for byoda.net creates a DNS record for each pod based on the ACCOUNT_ID of the pod. The ACCOUNT_ID is stored in the ~/.byoda-account_id file on your VM/server. The FQDN is '<ACCOUNT_ID>.accounts.byoda.net'. Make sure to save this ACCOUNT_ID as well to a secure place
- You can log into the web-interface of the pod using basic auth via the account FQDN. You will get a warning in your browser about a certificate signed by an unknown CA but you can ignore the warning. The username is the first 8 characters of your ACCOUNT_ID, as shown in the output of the ```tools/set_env.sh``` script and the password is the string you've set for the ACCOUNT_SECRET variable in the docker-launch.sh script. You can use it a.o. to browse the OpenAPI docs ('/docs/' and '/redoc/') of your pod.

## Using the pod with the 'Address Book' service

The 'Address Book' service is a proof of concept on how a service in the BYODA network can operate. Control of the pod and accessing its data uses REST APIs. Using the [tools/call_data_api.py](https://github.com/byoda/byoda-python/blob/master/tools/call_data_api.py) tool you can interface with the data storage in the pod without having to know mess around with certificates and JSON. Copy the [set_env.sh](https://github.com/byoda/byoda-python/blob/master/tools/set_env.sh) to the same directory as the docker-launch.sh script on your VM / server and source it:

```bash
source tools/set_env.sh
```

Now that we have all the bits and pieces in place, let's first see what services are available on the byoda.net network:

```bash
curl -s https://dir.byoda.net/api/v1/network/services | jq .
```

Currently there is only a test service called 'address book'. We can use curl to confirm that the pod has discovered this service in the network:

```bash
curl -s --cacert $ROOT_CA --cert $ACCOUNT_CERT --key $ACCOUNT_KEY \
    --pass $PRIVATE_KEY_SECRET https://$ACCOUNT_FQDN:444/api/v1/pod/account | jq .
```

We can make our pod join the address book service:

```bash
curl -s -X POST --cacert $ROOT_CA --cert $ACCOUNT_CERT --key $ACCOUNT_KEY \
     --pass $PRIVATE_KEY_SECRET \
    https://$ACCOUNT_FQDN:444/api/v1/pod/member/service_id/$SERVICE_ADDR_ID/version/1 | jq .
```

The pod returns amongst others the cert & key that you can use to call the APIs on the pod for that specific membershp.

We can confirm that our pod has joined the service with:

```bash
curl -s --cacert $ROOT_CA --cert $ACCOUNT_CERT --key $ACCOUNT_KEY --pass $PRIVATE_KEY_SECRET \
    https://$ACCOUNT_FQDN:444/api/v1/pod/member/service_id/$SERVICE_ADDR_ID | jq .
```

We quickly now update our environment variables to pick up the info about the new membership:

```bash
source tools/set_env.sh
```

You will need the Member ID later on in this introduction. When the pod becomes a member of a service, it creates a namespace for that service so that data from different services is isolated and one service can not access the data of the other service (unless you explicitly allow it to.)

Querying and submitting data to the pod uses the REST APIs. To facilitate inspecting and updating data while testing, we provide the [tools/call_data_api.py](https://github.com/byoda/byoda-python/blob/master/tools/call_data_api.py) tool. Whenever you want to store or update data in the pod, you need to supply a JSON file to the tool so it can submit that data. So let's put some data about us in our pod.

```bash
cat >/tmp/person.json <<EOF
{
    "given_name": "<your-name>",
    "family_name": "<your-family-name",
    "additional_names": "",
    "email": "<your email address>",
    "homepage_url": "",
    "avatar_url": ""
}
EOF

pipenv run tools/call_data_api.py --object person --action mutate --data-file /tmp/person.json
```

If you want to see your details again, you can run

```bash
pipenv run tools/call_data_api.py --object person --action query
```

and you'll see a bit more info than what you put in person.json as we only supplied the fields required by the data model of the 'address book' service:

```bash
{
  "total_count": 1,
  "edges": [
    {
      "cursor": "ac965dd4",
      "origin": "<your member ID>",
      "node": {
        "additional_names": null,
        "avatar_url": null,
        "email": "<your email>",
        "family_name": "<your family name>",
        "given_name": "<your name>",
        "homepage_url": null
    }
  ],
  "page_info": {
    "end_cursor": "ac965dd4",
    "has_next_page": false
  }
}
```

As a query for 'person' objects can result in more than one result, the output facilitates pagination. You can see in the output the 'node' object with the requested information.

Now suppose you want to follow me / my pod. The member ID of the Address Book service of one of my test pods is '94f23c4b-1721-4ffe-bfed-90f86d07611a'

```bash
cat >/tmp/follow.json <<EOF
{
    "member_id": "94f23c4b-1721-4ffe-bfed-90f86d07611a",
    "relation": "follow",
    "created_timestamp": "2022-07-04T03:50:26.451308+00:00"
}
EOF

pipenv run tools/call_data_api.py --object network_links --action append --data-file /tmp/follow.json
```

The 'Address Book' service has unidirectional relations. So the fact that you follow me doesn't mean I follow you back. But you can send me an invite to start following you:

```bash
cat >/tmp/invite.json <<EOF
{
    "created_timestamp": "2022-07-04T14:50:26.451308+00:00",
    "member_id": "<replace with your member_id>",
    "relation": "follow",
    "text": "Hey, why don't you follow me!"
}
EOF

pipenv run tools/call_data_api.py --object network_invites --action append --remote-member-id 94f23c4b-1721-4ffe-bfed-90f86d07611a --data-file /tmp/invite.json --depth 1
```

With the '--depth 1' and '--remote-member-id <uuid>' parameters, you tell your pod to connect to my pod and perform the 'append' action. So the data does not get stored in your pod but in mine! I could periodically review the invites I have received and perform 'appends' to my 'network_links' for the people that I want to accept the invitation to.

The reason that your pod is allowed to add data to my pod is because of the ['data contract' of the 'address book' service](https://github.com/byoda/byoda-python/blob/master/tests/collateral/addressbook.json). In there, you can find:

```bash
    "network_invites": {
        "#accesscontrol": {
            "member": {
                "permissions": ["read", "update", "delete", "append"]
            },
            "any_member": {
                "permissions": ["append"]
            }
        },
        "type": "array",
        "items": {
            "$ref": "/schemas/network_invite"
        }
    },
```

The 'any_member' access control allows any member of the address book service to append entries to the array of 'network_invites' but only you as the 'member' of the address book service and owner of the pod, can read, update and delete from this array.

If you look at the 'network_assets' data structure in the JSON file, you see:

```bash
    "network_assets": {
        "#accesscontrol": {
            "member": {
                "permissions": ["read", "delete", "append"]
            },
            "network": {
                "permissions": ["read"],
                "distance": 1
            }
        },
        "type": "array",
        "items": {
            "$ref": "/schemas/asset"
        }
    }
```

This means that once I have accepted your invite by adding an entry to my 'network_links' array, you can query my 'network_assets' and read my posts, tweets or video uploads that I have decided to add to the 'network_assets' array.

With the 'distance: 1' parameter, only people that I have entries for in my 'network_links' array can see those assets. But in the same JSON, you can see the 'service_assets' array with access control

```bash
    "any_member": {
        "permissions": ["read"]
    }
```

and any member of the address book service will be able to query entries from that array. The 'network_links' array of objects is a special case in any datamodel as the pod will use the data in that array to evaluate the definition for 'network' access in the "#accesscontrol" clauses.
Today, the max distance for network queries is '1' so you can only query the pods that have a network_link with you. In the future we'll explore increasing the distance while maintaining security and keeping the network scalable and performant.

As you have seen in the requests to the data API, the pod implements the data model of the address book. The data API is documented using OpenAPI. You can browse the APIs by pointing your browser the URL listed in the 'OpenAPI redoc' line of the output of 'source tools/set-env.sh', ie.:

```bash
https://proxy.byoda.net/4294929430/${YOUR_MEMBER_ID}/redoc
```

While the initial test service is the 'address book', your pod is not restricted to the 'address book' data model! You can create your own service and define its data contract in a [JSONSchema](https://www.json-schema.org/) document. When your pod reads that data contract it will automatically generate the Data APIs for that data contract. Any pod that has also joined your service and accepted that data model will then be able to call those Data APIs on other pods that have also accepted it. The pods will implement the security model that you have defined with "#accesscontrol" objects of your datamodel.

## Access security

When pods communicate with each other, they use Mutual-TLS with certificates signed by the CA of the byoda.net network. Mutual-TLS provides great security but because web browsers do not know the byoda.net CA, so we can't use M-TLS with browsers. For browsers we use JWTs. If you use a custom domain, the pod will generate a Let's Encrypt TLS certificate so you can connect with your browser and the JWT to your pod. If you do not have a custom domain then browsers will not recognize the CA hierarchy that Byoda uses. For this use case, the byoda.net network hosts a proxy at proxy.byoda.net.

To acquire a JWT for managing the pod, you get an 'account JWT'. If you do not use a custom domain then use:

```bash
export ACCOUNT_JWT=$( \
    curl -s \
    -d "{\"username\": \"${ACCOUNT_USERNAME}\", \"password\":\"${ACCOUNT_PASSWORD}\", \"target_type\":\"accounts\"}" \
    -H "Content-Type: application/json" \
    https://proxy.byoda.net/$ACCOUNT_ID/api/v1/pod/authtoken | jq -r .auth_token
); echo $ACCOUNT_JWT
```

If you use a custom domain, you can not use the proxy and have to use the custom domain for calling account APIs:

```bash
CUSTOM_DOMAIN=<changeme>
export ACCOUNT_JWT=$( \
    curl -s \
    -d "{\"username\": \"${ACCOUNT_USERNAME}\", \"password\":\"${ACCOUNT_PASSWORD}\", \"target_type\":\"accounts\"}" \
    -H "Content-Type: application/json" \
    https://${CUSTOM_DOMAIN}/api/v1/pod/authtoken | jq -r .auth_token \
); echo $ACCOUNT_JWT
```

You can use the 'account' JWT to call REST APIs on the POD, ie.:

```bash
curl -s --cacert $ROOT_CA -H "Authorization: bearer $ACCOUNT_JWT" \
    https://$ACCOUNT_FQDN/api/v1/pod/account | jq .
```

or, if you use a custom domain:

```bash
curl -s -H "Authorization: bearer $ACCOUNT_JWT" \
    https://${CUSTOM_DOMAIN}/api/v1/pod/account | jq .
```

If you need to call the Data API, you need to have a 'member' JWT:

```bash
export MEMBER_JWT=$( \
    curl -s \
    -d "{\"username\": \"${MEMBER_USERNAME}\", \"password\":\"${ACCOUNT_PASSWORD}\", \"service_id\":\"${SERVICE_ADDR_ID}\"}" \
    -H "Content-Type: application/json" \
     https://proxy.byoda.net/$SERVICE_ADDR_ID/$MEMBER_ID/api/v1/pod/authtoken | jq -r .auth_token); echo $MEMBER_JWT
```

or with custom domain:

```bash
export MEMBER_JWT=$( \
    curl -s \
    -d "{\"username\": \"${MEMBER_USERNAME}\", \"password\":\"${ACCOUNT_PASSWORD}\", \"service_id\":\"${SERVICE_ADDR_ID}\"}" \
    -H "Content-Type: application/json" \
     https://${CUSTOM_DOMAIN}/api/v1/pod/authtoken | jq -r .auth_token); echo $MEMBER_JWT
```

You can use the member JWT to query Data API on the pod. While you can call the Data API using curl, generating the queries gets tedious. For that reason, we provide the [tools/call_data_api.py](https://github.com/byoda/byoda-python/blob/master/tools/call_data_api.py).

A BYODA service doesn't just consist of a data model and namespaces and APIs on pods. A service also has to host a server that hosts some required APIs. The service can optionally host additional APIs such as, for example, a 'search' service to allow members to discover other members. You can not use the member-JWT generated previously to call REST APIs against the server for the service, as that JWT can only be used with your pod. To get a JWT you can use to authenticate against the service API, you can execute:

```bash
export MEMBER_JWT=$( \
    curl -s \
    -d "{\"username\": \"${MEMBER_USERNAME}\", \"password\":\"${ACCOUNT_PASSWORD}\", \"service_id\":\"${SERVICE_ADDR_ID}\", \"target_type\":\"service-\"}" \
    -H "Content-Type: application/json" \
     https://proxy.byoda.net/$SERVICE_ADDR_ID/$MEMBER_ID/api/v1/pod/authtoken | jq -r .auth_token); echo $MEMBER_JWT
```

or, with custom domain:

```bash
export MEMBER_JWT=$( \
    curl -s \
    -d "{\"username\": \"${MEMBER_USERNAME}\", \"password\":\"${ACCOUNT_PASSWORD}\", \"service_id\":\"${SERVICE_ADDR_ID}\", \"target_type\":\"service-\"}" \
    -H "Content-Type: application/json" \
     https://${CUSTOM_DOMAIN}/api/v1/pod/authtoken | jq -r .auth_token); echo $MEMBER_JWT
```

With this JWT for calling APIs of the service, we can call the _search_ API of the address book service

```bash
curl -s --cacert $ROOT_CA --cert $MEMBER_ADDR_CERT --key $MEMBER_ADDR_KEY --pass $PRIVATE_KEY_SECRET \
    https://service.service-$SERVICE_ADDR_ID.byoda.net/api/v1/service/search/email/steven@byoda.org  | jq .
```

In the address book schema, services are allowed to send requests to pods and collect their member ID and e-mail address because for the 'email' property of the 'person' object, we have:

```bash
    "email": {
        "format": "idn-email",
        "type": "string",
        "#accesscontrol": {
            "service": {
                "permissions": ["search:exact-caseinsensitive"]
            }
        }
    },
```

When services are allowed by their service contract to collect data from pods, they have to commit to not persist the data on their systems. They may cache the data in-memory for 72 hours but after that it must be automatically removed from the cache and the service will have to request the data from the pod again. This will allow people to keep control over their data while enabling people to discover other people using the service. For the _search_ API of the address book service, this is implemented by a worker process that periodically calls the pods, gets the data, and stores it in a Redis cache with an expiration of 72 hours.

## Certificates and browsers

In the setup described above, when not using a custom domain, browsers do not know about the Certificate Authority (CA) used by byoda.net and will throw a security warning when they connect directly to a pod. There are a couple of solutions for this problem, each with their own pros and cons:

### Use a Byoda proxy

Point your browser to https://proxy.byoda.net/[service-id]/[member-id] and https://proxy.byoda.net/[account-id] and it will proxy your requests to your pod. The downside of this solution is that the proxy decrypts and re-encrypts all traffic. This includes the username/password you use to get a security token and the security token itself. Even if you trust us not to intercept that traffic, the proxy could be compromised and hackers could then configure it to intercept the traffic. As we are still in the early development cycles of Byoda, we believe this is a acceptable risk. After all, you also send your username and password to websites when you log in to those websites so it is a similar security risk.

### Custom domain

 Instead of using the proxy, you can use a custom domain with your pod. When you provide a custom domain using the CUSTOM_DOMAIN environment variable to your pod, the pod will:

- Request a TLS certificate from Let's Encrypt for the specified domain
- Create a virtual webserver for the domain
- Periodically renew the certificate (Let's Encrypt sets expiration of certicates it signs to 90 days)

The benefit is that you can connect with your browser directly to your pod but you'll need to register and manage a domain with a domain registrar.

The procedure to use a custom domain is:

1. Create the VM to run the pod on, note down its public IP address (ie. with ```curl ifconfig.co``` on the vm). As Let's Encrypt uses port 80 to validate the request for a certificate, port 80 of your pod must be accessible from the Internet. If you followed the procedure to create a VM from the documentation then port 80 is already accessible from the Internet
2. Register a domain with a domain registry, here we'll use 'example.org'
3. Update the DNS records for your domain so that 'byoda.example.org' has an 'A' record for the public IP address of your pod
4. Update the 'docker-launch.sh' script to set the CUSTOM_DOMAIN variable
5. Run the 'docker-launch.sh' script to (re-)start your pod. This script will check your DNS setup and will not start the pod if the CUSTOM_DOMAIN variable is set but the DNS record for the domain does not point to the public IP of the pod.

You can now point your browser to your pod: <https://byoda.example.org> (or the dns record you actually created.)

## Youtube import

To enable the import of the metadata of YouTube videos from your YouTube channel, set the environment variable ```YOUTUBE_CHANNEL``` to the name of the your channel. There are two ways that the pod can import your videos:

- Scraping from the YouTube website: with this method, only the videos on the main page of your channel get imported.
- Using the YouTube Data API. This requires you to create a YouTube DATA API key. You can follow [these instructions](https://medium.com/mcd-unison/youtube-data-api-v3-in-python-tutorial-with-examples-e829a25d2ebd) to create the API key. Then set the ```YOUTUBE_API_KEY``` environment variable and restart the pod container.

YouTube applies a quota of 10000 'credits' per day. The 'search' API that the pod_worker uses consumes 100 credits so you do not want to call the API more than 100 times per day. By default, the pod worker runs an import once per 4 hours. You can set the ```YOUTUBE_IMPORT_INTERVAL``` environment to the interval in minutes that you want the pod_worker to run the import process. YouTube returns a maximum of 50 videos per API call. If you have more than 50 videos in your channel then the pod worker will call the API multiple times until it has imported all videos or until it finds a video that has already been imported. So the first time you run the importer, it could make multiple API calls but in subsequent runs it would call the API just once per run.

To set the environment variables, you can edit the ```byoda-settings.sh``` file that gets sourced by the ```docker-launch.sh script```

```bash
# To import your YouTube videos, edit the following variables:
export YOUTUBE_CHANNEL=

# To import using the YouTube API instead of scraping it from the YouTube website,
# set the following variable to your API key:
export YOUTUBE_API_KEY=

# To manage how often the import process runs, set the following variable
export YOUTUBE_IMPORT_INTERVAL=240
```

If you just set the *YOUTUBE_CHANNEL* to the name of your channel then only the metadata of your YouTube videos will be ingested but the playback URL will point to youtube.com. If you specify _<channel-name>:ALL_ then the pod will additionally ingest all the video and audio files and store it in your AWS/GCP storage bucket of Azure storage-account. The playback URL will then point to the byoda CDN (cdn.byo.host), which will fetch the content from your the angie server running in your pod, which will retrieve the requested content from your storage-bucket/account. Keep in mind that ingesting the video and audio files will incur costs for your storage account. Streaming the content via the CDN and your pod will incur cloud costs for the network traffic of both your pod and your storage account.

## TODO

The byoda software is currently alpha quality. There are no web UIs or mobile apps yet. curl and 'call-data_api' are currently the only user interface.

The main areas of development are:

- generating your feed/timeline in the pod
- set up a proof-of-concept Tube service
- support access control based on memberships of 'groups'
- data ACLs for specific UUIDs
- Implementing the 'network:+n' construct (with n>1) for the access permissions in the JSON Schema to allow people in your network to query your Data APIs.
- create algorithms that you can run to collect data from your pod, the pods of your network and APIs hosted by the service to generate a feed of content for you.
