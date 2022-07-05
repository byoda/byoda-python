# Bring your own data & algorithms

## Intro
Byoda is a new and radically different social media platform:
- Your data is stored in your own personal data store (or 'pod').
- Access to your data is controlled by a __data contract__ and is enforced by a __data firewall__.
- You can select the algorithm(s) that generate your content feed for you.
- You can store your unique content in your own pod and monetize it.
- Anyone can develop apps and services on the platform.
- The code for the reference implementation of the various components is open source.

This repo hosts the reference implementation (in Python) of the Byoda directory server, a generic 'service' server and the data pod. For more information about Byoda, please go to the [web site](https://www.byoda.org/)

## Status
This is alpha-quality software. The only user interface available is curl. The byoda.net network is running, a proof-of-concept service 'Address Book' is up and running and you can install the data pod on a VM in AWS, Azure or GCP or on a server in your home.

## Getting started with the data pod
There are two ways to install the pod:
1. Use a public cloud like Amazon Web Services, Microsoft Azure or Google Cloud.
    - Create an account with the cloud provider of choice
    - Create a VM with a public IP address, The VM should have at least 1GB of memory and 8GB of disk space.
    - Create two buckets (AWS/GCP) or storage accounts (Azure).
        - Pick a random string (ie. 'mybyoda') and the name of the storage accounts must then be that string appended with '-private' and '-public', (ie.: 'mybyoda-private' and 'mybyoda-public').
        - Disable public access to the '-private' bucket or storage-account. If the cloud has the option available, specify uniform access for all objects.
        - Use 'managed-identity'-based access to grant the VM full access to the buckets/storage-accounts.
    - The HTTPS port for the public IP must be accessible from the Internet and the SSH port must be reachable from your home IP address (or any other IP address you trust).
    - Running the VM, its public IP address and the storage may incur costs, unless you manage to stay within the limits of the free services offered by:
        - [AWS](https://aws.amazon.com/free), consider using the t2.micro SKU for the VM.
        - [Azure](https://azure.microsoft.com/en-us/free/), consider using the B1s SKU for the VM.
        - [GCP](https://cloud.google.com/free/), consider using the e2-micro SKU for the VM.
2. Install the pod as a docker container in a server in your home.
    - Ports 443 on your server must be available for the pod to use and must be accessible from the Internet
    - Carefully consider the security implementations on enabling port forwarding on your broadband router and whether this is the right setup for you.

To launch the pod:
- If you want to deploy to a VM, follow the instructions for [AWS](https://github.com/StevenHessing/byoda-python/blob/master/docs/infrastructure/aws-vm-pod.md), [Azure](https://github.com/StevenHessing/byoda-python/blob/master/docs/infrastructure/azure-vm-pod.md) or [GCP](https://github.com/StevenHessing/byoda-python/blob/master/docs/infrastructure/gcp-vm-pod.md))
- Log in to your VM or server.
- Copy the [docker-launch.sh script](https://github.com/StevenHessing/byoda-python/blob/master/tools/docker-lauch.sh) to the VM
- Edit the docker-launch.sh script and modify the following variables at the top of the script
  - BUCKET_PREFIX: in the above example, that would be 'mybyoda'
  - ACCOUNT_SECRET: set it to a long random string; it can be used as credential for browsing your pod
  - PRIVATE_KEY_SECRET: set it to a long random string; it will be used for the private keys that the pod will create
- for a pod on an AWS VM, also edit the variables:
  - AWS_ACCESS_KEY_ID
  - AWS_SECRET_ACCESS_KEY
- Install the docker, uuid and jq packages and launch the pod

```
sudo apt update && apt-get install -y docker.io uuid jq
chmod 755 docker-launch.sh
./docker-launch.sh
```

**Congratulations, you now have a running pod that is member of the byoda.net network!** <br>


## Basic info about the pod
- The logs of the pod are stored in /var/www/wwwroot/logs. This directory is volume-mounted in the pod. The certs and data files are stored in the cloud or locally on your server. In either case, are (also) availble under /byoda, which is also volume-mounted in the pod.<br>
- The 'directory server' for byoda.net creates a DNS record for each pod based on the ACCOUNT_ID of the pod. The ACCOUNT_ID is stored in the ~/.byoda-account_id file on your VM/server. The FQDN is '<ACCOUNT_ID>.accounts.byoda.net'.
- You can log into the web-interface of the pod using basic auth via the account FQDN. You will get a warning in your browser about a certificate signed by an unknown CA but you can ignore the warning. The username is the first 8 characters of your ACCOUNT_ID and the password is the string you've set for the ACCOUNT_SECRET variable in the docker-launch.sh script. You can use it to browse the OpenAPI docs ('/docs/' and '/redoc/') of your pod.

## Using the pod with the 'Address Book' service
The 'Address Book' service is a proof of concept on how a service in the BYODA network can operate. Control of the pod uses REST APIs while access to data in the pod uses [GraphQL](https://graphql.org/). Using the tools/call_graphql.py tool you can interface with the data storage in the pod without having to know GraphQL. Copy the [set_envenv.sh](https://github.com/StevenHessing/byoda-python/blob/master/docs/files/set_env.sh) to the same directory as the docker-launch.sh script on your VM / server and source it:
```
sudo chmod -R a+r /byoda
sudo apt install python3-pip
sudo pip3 install --upgrade orjson aiohttp jsonschema requests
git clone https://github.com/StevenHessing/byoda-python.git
cd byoda-python
export PYTHONPATH=$PYTHONPATH:.
source tools/setenv.sh
```
Let's first see what services are available on the byoda.net network:
```
curl -s https://dir.byoda.net/api/v1/network/services | jq .
```

Now we can use curl to get the list of services the pod has discovered in the network:
```
curl -s --cacert $ROOT_CA --cert $ACCOUNT_CERT --key $ACCOUNT_KEY \
    --pass $PASSPHRASE https://$ACCOUNT_FQDN/api/v1/pod/account | jq .
```

We can make our pod join the address book service:
```
curl -s -X POST --cacert $ROOT_CA --cert $ACCOUNT_CERT --key $ACCOUNT_KEY \
     --pass $PASSPHRASE \
    https://$ACCOUNT_FQDN/api/v1/pod/member/service_id/$SERVICE_ADDR_ID/version/1 | jq .
```

We can confirm that our pod has joined the service with:
```
curl -s --cacert $ROOT_CA --cert $ACCOUNT_CERT --key $ACCOUNT_KEY --pass $PASSPHRASE \
    https://$ACCOUNT_FQDN/api/v1/pod/member/service_id/$SERVICE_ADDR_ID | jq .
```

We quickly now update our environment variables to pick up the new membership:
```
source tools/setenv.sh
echo $MEMBER_ID
```

You will need that member ID later on in this tutorial
The call-graphql.py tool can be used to interact with data storage in the pod. Whenever you want to store or update data in the pod, you need to supply a JSON file to the tool so it can submit that data. So let's put some data about us in our pod

```
cat >person.json <<EOF
{
    "given_name": "<your name>",
    "family_name": "<your family name>",
    "email": "<your email>"
}
EOF

tools/call_graphql.py --class-name person --action mutate --data-file person.json
```

If you want to see your details again, you can run
```
tools/call_graphql.py --class-name person --action query
```
and you'll see a bit more info than you requested:
```
{
  "person_connection": {
    "total_count": 1,
    "edges": [
      {
        "cursor": "ac965dd4",
        "origin": "<your member ID>",
        "person": {
          "additional_names": null,
          "avatar_url": null,
          "email": "<your email>",
          "family_name": "<your family name>",
          "given_name": "<your name>",
          "homepage_url": null
        }
      }
    ],
    "page_info": {
      "end_cursor": "ac965dd4",
      "has_next_page": false
    }
  }
}
```
As a query for person can result in more than one result, the output facilitates pagination. You can see in the output the 'person' object with the requested informaiton.

Now suppose you want to follow me. The member ID of the Address Book service of one of my test pods is '86c8c2f0-572e-4f58-a478-4037d2c9b94a'
```
cat >follow.json <<EOF
{
    "member_id": "86c8c2f0-572e-4f58-a478-4037d2c9b94a",
    "relation": "follow",
    "timestamp": "2022-07-04T03:50:26.451308+00:00"
}
EOF

tools/call_graphql.py --class-name network_links --action append
```

The address book has unidirectional relations. So the fact that you follow me doesn't mean I follow you back. But you can send me an invite to start following you:
```
cat >invite.json <<EOF
{
    "timestamp": "2022-07-04T14:50:26.451308+00:00",
    "member_id": "89936493-ec56-4c38-971d-cab1179d1a01",
    "relation": "follow",
    "text": "Hey, why don't you follow me!"
}
EOF

tools/call_graphql.py --class-name network_invites --action append --remote-member-id 86c8c2f0-572e-4f58-a478-4037d2c9b94a  --data-file ~/invite.json --depth 1
```

With the '--depth 1' and '--remote-member-id <uuid>' parameters, you tell your pod to connect to my pod and perform the 'append' action. So the data does not get stored in your pod but in mine! I could periodically review the invites I have received and perform 'appends' to my 'network_links' for the people that I want to accept the invitation to.

The reason that your pod is allowed to add data to my pod is because of the [data definitions of the 'address book' service](https://github.com/StevenHessing/byoda-python/blob/master/tests/collateral/addressbook.json). In there, you can find:
```
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

The 'any_member' access control allows any member of the address book service to append entries to the array of 'network_invites' but only you as the 'member', can read, update and delete from this array.

If you look at the 'network_assets' data structure in the JSON file, you see:
```
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
```
    "any_member": {
        "permissions": ["read"]
    }
```
and any member of the address book service will be able to query entries from that array.

As you see, the pod implements the data model of the address book and provides a GraphQL interface for it. You can browse to the GraphQL web-interface directly by pointing your browser the URL listed in the last line of the output of 'set-env.sh', ie.:
```
https://89936493-ec56-4c38-971d-cab1179d1a01.members-4294929430.byoda.net/api/v1/data/service-4294929430
```

But your pod is not restricted to the 'address book' data model! You can create your own service and define its datamodel in [JSONSchema](https://www.json-schema.org/). When your pod reads that data model it will automatically generate the GraphQL APIs for that datamodel. You can use the [generate_graphql_queries.py](https://github.com/StevenHessing/byoda-python/blob/master/tools/generate_graphql_queries.py) tool to generate the GraphQL queries for your data model. Any pod that has also joined your service and accepted that data model will then be able to call those GraphQL APIs on other pods that have also accepted it.


curl -s -X POST -H 'content-type: application/json' \
    --cacert $ROOT_CA --cert $MEMBER_ADDR_CERT --key $MEMBER_ADDR_KEY --pass $PASSPHRASE \
    https://$MEMBER_ADDR_FQDN/api/v1/data/service-$SERVICE_ADDR_ID \
    --data @person-query | jq .
```
It will take a while for the address book service to retrieve your data from your pod and make it available from its search API. The address book service queries a pod every 10 seconds so, the exact time depends on how many people have joined the service. In the meantime, you can call the search API to find the member_id of my email address: steven@byoda.org
```
curl -s --cacert $ROOT_CA --cert $MEMBER_ADDR_CERT --key $MEMBER_ADDR_KEY --pass $PASSPHRASE \
	https://service.service-$SERVICE_ADDR_ID.byoda.net/api/v1/service/search/steven@byoda.org  | jq .
```
Let's note the member_id from the output of the previous command and tell your pod to add me as your friend:
```
curl -s -X POST -H 'content-type: application/json' \
    --cacert $ROOT_CA --cert $MEMBER_ADDR_CERT --key $MEMBER_ADDR_KEY --pass $PASSPHRASE \
    https://$MEMBER_ADDR_FQDN/api/v1/data/service-$SERVICE_ADDR_ID \
    --data '{"query": "mutation { append_network_links( member_id: \"5890cede-6799-46f4-9357-986cd45f6909\", relation: \"friend\", timestamp: \"2022-07-02T03:30:27.180230+00:00\") {  member_id relation timestamp } }" }' | jq .
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
export MEMBER_JWT=$(curl -s --basic --cacert $ROOT_CA -u $MEMBER_USERNAME:$ACCOUNT_PASSWORD https://$MEMBER_ADDR_FQDN/api/v1/pod/authtoken/service_id/$SERVICE_ADDR_ID | jq -r .auth_token); echo $MEMBER_JWT
```
You can use the member JWT to query GraphQL API on the pod:
```
curl -s -X POST -H 'content-type: application/json' \
    --cacert $ROOT_CA -H "Authorization: bearer $MEMBER_JWT" \
    https://$MEMBER_ADDR_FQDN/api/v1/data/service-$SERVICE_ADDR_ID \
    --data '{"query": "query {person_connection {edges {person {given_name additional_names family_name email homepage_url avatar_url}}}}"}'
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
- Implementing the 'network:+n' construct for the access permissions in the JSON Schema to allow people in your network to query your GraphQL APIs.
- Improve the support for complex data structures in the data contract.
- Add API to upload content to the public object storage

