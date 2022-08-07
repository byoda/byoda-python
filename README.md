# Bring your own data & algorithms

## Intro
Byoda is a personal data store with features enabling a new and radically different social media services:
- Your data is stored in your own personal data store (or 'pod').
- Access to your data is controlled by a __data contract__ and is enforced by a __data firewall__.
- You can select the algorithms that generate your content feed for you.
- You will be able store your unique content in your own pod and monetize it.
- Anyone can develop apps and services on the platform.
- The code for the reference implementation of the various components is open source.

This repo hosts the reference implementation (in Python) of the Byoda directory server, a generic 'service' server and the data pod. For more information about Byoda, please go to the [web site](https://www.byoda.org/)

## Status
This is alpha-quality software. The only user interface available today is curl and a tool to call GraphQL APIs. If you don't know what curl is, this software is probably not yet mature enough for you. The byoda.net network is running, a proof-of-concept service 'Address Book' is up and running and you can install the data pod on a VM in AWS, Azure or GCP or on a server in your home.

## Getting started with the data pod
There are two ways to install the pod:
1. Use a public cloud like Amazon Web Services, Microsoft Azure or Google Cloud.
    - Create an account with the cloud provider of choice
    - Create a VM with a public IP address, The VM should have at least 1GB of memory and 8GB of disk space.
    - Create two buckets (AWS/GCP) or storage accounts (Azure).
        - Pick a random string (ie. 'mybyoda') and the name of the storage accounts must then be that string appended with '-private' and '-public', (ie.: 'mybyoda-private' and 'mybyoda-public').
        - Disable public access to the '-private' bucket or storage-account. If the cloud has the option available, specify uniform access for all objects.
    - Follow the cloud-specific instructions for creating the VM to run the pod on
        - [AWS](https://github.com/StevenHessing/byoda-python/blob/master/docs/infrastructure/aws-vm-pod.md)
        - [Azure](https://github.com/StevenHessing/byoda-python/blob/master/docs/infrastructure/azure-vm-pod.md)
        -  [GCP](https://github.com/StevenHessing/byoda-python/blob/master/docs/infrastructure/gcp-vm-pod.md)
    - The HTTPS port for the public IP must be accessible from the Internet and the SSH port must be reachable from your home IP address (or any other IP address you trust).
    - Running the VM, its public IP address and the storage may incur costs, unless you manage to stay within the limits of the free services offered by:
        - [AWS](https://aws.amazon.com/free), consider using the t2.micro SKU for the VM.
        - [Azure](https://azure.microsoft.com/en-us/free/), consider using the B1s SKU for the VM.
        - [GCP](https://cloud.google.com/free/), consider using the e2-micro SKU for the VM.
2. Install the pod as a docker container in a server in your home.
    - Ports 443 on your server must be available for the pod to use and must be accessible from the Internet
    - Carefully consider the security implications of enabling port forwarding on your broadband router and whether this is the right setup for you.

To launch the pod:
- Log in to your VM or server.
- Clone the [byoda repository](https://github.com/StevenHessing/byoda-python.git)

```
sudo apt update && sudo apt-get install -y docker.io uuid jq git vim python3-pip
git clone https://github.com/StevenHessing/byoda-python.git
```

- Copy and edit the tools/docker-launch.sh script and modify the following variables at the top of the script
    - BUCKET_PREFIX: in the above example, that would be 'mybyoda'
    - ACCOUNT_SECRET: set it to a long random string; it can be used as credential for browsing your pod
    - PRIVATE_KEY_SECRET: set it to a long random string; it will be used for the private keys that the pod will create
  - if you deployed a VM on AWS, also edit the variables:
    - AWS_ACCESS_KEY_ID
    - AWS_SECRET_ACCESS_KEY
  - Make sure to save the values for ACCOUNT_SECRET and PRIVATE_KEY_SECRET to a secure place as without them, you have no way to recover the data in your pod if things go haywire.

```
cd byoda-python
cp tools/docker-launch.sh ~
vi ~/docker-launch.sh
```

- Now run the docker-launch.sh script

```
~/docker-launch.sh
```

**Congratulations, you now have a running pod that is a member of the byoda.net network!** <br>


## Basic info about the pod
- The logs of the pod are stored in /var/www/wwwroot/logs. This directory is volume-mounted in the pod. The certs and data files are stored in the cloud or locally on your server. In either case, are (also) availble under /byoda, which is also volume-mounted in the pod.<br>
- The 'directory server' for byoda.net creates a DNS record for each pod based on the ACCOUNT_ID of the pod. The ACCOUNT_ID is stored in the ~/.byoda-account_id file on your VM/server. The FQDN is '<ACCOUNT_ID>.accounts.byoda.net'. Make sure to save this ACCOUNT_ID as well to a secure place
- You can log into the web-interface of the pod using basic auth via the account FQDN. You will get a warning in your browser about a certificate signed by an unknown CA but you can ignore the warning. The username is the first 8 characters of your ACCOUNT_ID and the password is the string you've set for the ACCOUNT_SECRET variable in the docker-launch.sh script. You can use it a.o. to browse the OpenAPI docs ('/docs/' and '/redoc/') of your pod.

## Using the pod with the 'Address Book' service
The 'Address Book' service is a proof of concept on how a service in the BYODA network can operate. Control of the pod uses REST APIs while access to data in the pod uses [GraphQL](https://graphql.org/). Using the tools/call_graphql.py tool you can interface with the data storage in the pod without having to know GraphQL. Copy the [set_envenv.sh](https://github.com/StevenHessing/byoda-python/blob/master/tools/set_env.sh) to the same directory as the docker-launch.sh script on your VM / server and source it:
```
sudo mkdir /byoda 2>/dev/null
sudo pip3 install --upgrade orjson aiohttp jsonschema requests \
    python_graphql_client certvalidator sqlalchemy passgen \
    starlette starlette-context python-json-logger
source tools/set_env.sh
```
Now that we have all the bits and pieces in place, let's first see what services are available on the byoda.net network:
```
curl -s https://dir.byoda.net/api/v1/network/services | jq .
```
Currently there is only a test service called 'address book'. We can use curl to confirm that the pod has discovered this service in the network:
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
The pod returns amongst others the cert & key that you can use to call the APIs on the pod for that specific membershp.

We can confirm that our pod has joined the service with:
```
curl -s --cacert $ROOT_CA --cert $ACCOUNT_CERT --key $ACCOUNT_KEY --pass $PASSPHRASE \
    https://$ACCOUNT_FQDN/api/v1/pod/member/service_id/$SERVICE_ADDR_ID | jq .
```

We quickly now update our environment variables to pick up the new membership:
```
source tools/set_env.sh
```
You will need the Member ID later on in this introduction. When the pod becomes a member of a service, it creates a namespace for that service so that data from different services is isolated and one service can not access the data of the other service, unless you explicitly allow it to.

Querying and sumitting data to the pod uses the [GraphQL language](https://graphql.org/). As the GraphQL language has a learning curve, we provide the 'call-graphql.py' tool to initially interact with data storage in the pod. Whenever you want to store or update data in the pod, you need to supply a JSON file to the tool so it can submit that data. So let's put some data about us in our pod

```
cat >~/person.json <<EOF
{
    "given_name": "<your name>",
    "family_name": "<your family name>",
    "email": "<your email>"
}
EOF

tools/call_graphql.py --object person --action mutate --data-file ~/person.json
```

If you want to see your details again, you can run
```
tools/call_graphql.py --object person --action query
```

and you'll see a bit more info than what you put in person.json as we only supplied the fields required by the data model of the 'address book' service:
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

As a query for 'person' objects can result in more than one result, the output facilitates pagination. You can see in the output the 'person' object with the requested information. The pagination implementation follows the [best practices defined by the GraphQL community](https://graphql.org/learn/pagination/).

Now suppose you want to follow me. The member ID of the Address Book service of one of my test pods is 'dd8dfb20-7c22-4ea0-9341-ae997b242e1278'
```
cat >~/follow.json <<EOF
{
    "member_id": "dd8dfb20-7c22-4ea0-9341-ae997b242e1278",
    "relation": "follow",
    "created_timestamp": "2022-07-04T03:50:26.451308+00:00"
}
EOF

tools/call_graphql.py --object network_links --action append --data-file ~/follow.json
```

The 'Address Book' service has unidirectional relations. So the fact that you follow me doesn't mean I follow you back. But you can send me an invite to start following you:
```
cat >~invite.json <<EOF
{
    "created_timestamp": "2022-07-04T14:50:26.451308+00:00",
    "member_id": "a2e36bed-1bf8-4774-bc73-5f08a4bae27d",
    "relation": "follow",
    "text": "Hey, why don't you follow me!"
}
EOF

tools/call_graphql.py --object network_invites --action append --remote-member-id dd8dfb20-7c22-4ea0-9341-ae997b242e1278 --data-file ~invite.json --depth 1
```

With the '--depth 1' and '--remote-member-id <uuid>' parameters, you tell your pod to connect to my pod and perform the 'append' action. So the data does not get stored in your pod but in mine! I could periodically review the invites I have received and perform 'appends' to my 'network_links' for the people that I want to accept the invitation to.

The reason that your pod is allowed to add data to my pod is because of the ['data contract' of the 'address book' service](https://github.com/StevenHessing/byoda-python/blob/master/tests/collateral/addressbook.json). In there, you can find:
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

The 'any_member' access control allows any member of the address book service to append entries to the array of 'network_invites' but only you as the 'member' and owner of the pod, can read, update and delete from this array.

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
and any member of the address book service will be able to query entries from that array. The 'network_links' array of objects is a special case in any datamodel as the pod will use the data in that array to evaluate the definition for 'network' access in the "#accesscontrol" clauses.
Today, the max distance for network queries is '1' so you can only query the pods that have a network_link with you. In the future we'll explore increasing the distance while maintaining security and keeping the network scalable and performant.

As you have seen in the GraphQL queries, the pod implements the data model of the address book and provides a GraphQL interface for it. You can browse to the GraphQL web-interface directly by pointing your browser the URL listed in the last line of the output of 'source tools/set-env.sh', ie.:
```
https://proxy.byoda.net/4294929430/$MEMBER_ID/api/v1/data/service-4294929430
```


While the initial test service is the 'address book', your pod is not restricted to the 'address book' data model! You can create your own service and define its data contract in a [JSONSchema](https://www.json-schema.org/) document. When your pod reads that data contract it will automatically generate the GraphQL APIs for that data contract. You can use the [generate_graphql_queries.py](https://github.com/StevenHessing/byoda-python/blob/master/tools/generate_graphql_queries.py) tool to generate the GraphQL queries for your data contract. Any pod that has also joined your service and accepted that data model will then be able to call those GraphQL APIs on other pods that have also accepted it. The pods will implement the security model that you have defined with "#accesscontrol" objects in your datamodel.

## Access security
When pods communicate with each other, they use Mutual-TLS with certificates signed by the CA of the byoda.net network. Mutual-TLS provides great security but because web browsers do not know the byoda.net CA, we can't use it with browsers. For browsers we use JWTs. However, when you connect to a pod directly you have to use Mutual-TLS for authentication. So for browsers, the byoda.net network hosts a proxy a proxy.byoda.net. When you use the proxy, you have to use the JWT for authentication because Mutual-TLS does not work as there is a level-7 HTTP proxy in between the two endpoints.
To acquire a JWT for managing the pod, you get an 'account JWT':
```
export ACCOUNT_JWT=$( \
    curl -s \
    -d "{\"username\": \"${ACCOUNT_USERNAME}\", \"password\":\"${ACCOUNT_PASSWORD}\"}" \
    -H "Content-Type: application/json" \
    https://proxy.byoda.net/$ACCOUNT_ID/api/v1/pod/authtoken | jq -r .auth_token
); echo $ACCOUNT_JWT
```

You can use the 'account' JWT to call REST APIs on the POD, ie.:
```
curl -s --cacert $ROOT_CA -H "Authorization: bearer $ACCOUNT_JWT" \
    https://$ACCOUNT_FQDN/api/v1/pod/account | jq .
```

If you need to call the GraphQL API, you need to have a 'member' JWT:
```
export MEMBER_JWT=$( \
    curl -s   \
    -d "{\"username\": \"${MEMBER_USERNAME}\", \"password\":\"${ACCOUNT_PASSWORD}\", \"service_id\":\"${SERVICE_ADDR_ID}\"}" \
    -H "Content-Type: application/json" \
     https://proxy.byoda.net/$SERVICE_ADDR_ID/$MEMBER_ID/api/v1/pod/authtoken | jq -r .auth_token); echo $MEMBER_JWT
```

You can use the member JWT to query GraphQL API on the pod:
```
curl -s -X POST -H 'content-type: application/json' \
    -H "Authorization: bearer $MEMBER_JWT" \
    https://proxy.byoda.net/$SERVICE_ADDR_ID/$MEMBER_ID/api/v1/data/service-$SERVICE_ADDR_ID \
    --data '{"query": "query {person_connection {edges {person {given_name additional_names family_name email homepage_url avatar_url}}}}"}' | jq .
```
A BYODA service doesn't just consist of a data model and namespaces and APIs on pods. A service also has to host an server that hosts some required APIs. The service can optionally host additional APIs such as a 'search' service to allow members to discover other members. You can  use the member-JWT to call REST APIs against the server for the service:
```
curl -s --cacert $ROOT_CA --cert $MEMBER_ADDR_CERT --key $MEMBER_ADDR_KEY --pass $PASSPHRASE \
	https://service.service-$SERVICE_ADDR_ID.byoda.net/api/v1/service/search/email/steven@byoda.org  | jq .
```

In the address book schema, services are allowed to send requests to pods and collect their member ID and e-mail address because for the 'email' property of the 'person' object, we have:
```
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

When services are allowed by their service contract to collect data from pods, they have to commit to not persist the data on their systems. They may cache the data in-memory for 48 hours but after that it must be automatically removed from the cache and the service will have to request the data from the pod again. This will allow people to keep control over their data while enabling people to discover other people using the service.

## Certificates and browsers

In the setup described above, browsers do not know about the Certificate Authority (CA) used by byoda.net and will throw a security warning when they connect directly to a pod. There are a couple of solutions for this problem, each with their own pros and cons:
### Use a Byoda proxy
Point your browser to https://proxy.byoda.net/[service-id]/[member-id] and https://proxy.byoda.net/[account-id] and it will proxy your requests to your pod. The downside of this solution is that the proxy decrypts and re-encrypts all traffic. This includes the username/password you use to get a security token and the security token itself. Even if you trust us not to intercept that traffic, the proxy could be compromised and hackers could then configure it to intercept the traffic. As we are still in the early development cycles of Byoda, we believe this is a acceptable risk. After all, you also send your username and password to websites when you log in to those websites so it is a similar security risk.

### Custom domain
 You can use a custom domain with your pod. When you provide a custom domain using the CUSTOM_DOMAIN environment variable to your pod, the pod will:
- Request a TLS certificate from Let's Encrypt for the specified domain
- Create a virtual webserver for the domain
- Periodically renew the certificate (Let's Encrypt sets expiration to 90 days)
The benefit is that you can connect with your browser directly to your pod but you'll need to register and manage a domain with a domain registrar.

The procedure to use a custom domain is:
0. Create the VM to run the pod on, note down its public IP address (ie. with ```curl ifconfig.co``` on the vm). As Let's Encrypt uses port 80 to validate the request for a certificate. Port 80 of your pod must be accessible from the Internet. If you followed the procedure to create a VM from the documentation then port 80 is already accessible from the Internet
1. Register a domain with a domain registry, here we'll use 'byoda.example.org'
2. Update the DNS records for your domain so that 'byoda.example.org' has an 'A' record for the public IP address of your pod
3. Update the 'docker-launch.sh' script to set the CUSTOM_DOMAIN variable
4. Run the 'docker-launch.sh' script to (re-)start your pod. This script will check your DNS setup and will not start the pod if the CUSTOM_DOMAIN variable is set but the DNS record for the domain does not point to the public IP of the pod.

## Twitter integration
To enable research into search and discovery on distributed social networks, the pod has the capability to import tweets from Twitter. This will give the byoda network an initial set of data to experiment with. To enable importing Tweets you have to sign up to the [Twitter Developer program](https://developer.twitter.com/en). Signing up is free and takes about a minute. You then go to the developer portal, create a 'project', select the project and then at the center top of the screen select 'Keys and tokens'. Generate an 'API key and secret' and write down those two bits. On your server, you can then edit the docker-launch.sh script and edit the following variables:
```
# Set this to the API key you generated on the Twitter Dev portal
export TWITTER_API_KEY=

# Set this to the secret you generated on the Twitter Dev portal
export TWITTER_KEY_SECRET=

# Select your own handle or, if you don't tweet much,
# set it to a handle of someone you like. Sample value: 'byoda_org'
export TWITTER_USERNAME=
```

When you launch the pod with these settings. A worker process in the pod will read the tweets from Twitter and store them in your pod. You can confirm that the tweets have been imported using the call-graphql tool:
```
cd byoda-python
export PYTHONPATH=.
source tools/set_env.sh
tools/call_graphql.py --object tweets --action query
```

When it is importing tweets, the worker in the pod will call a backend server of the 'address book' service to upload metadata about the tweets. This provides the data for a search API. At this time, you can call it to look for mentions or hashtags.
```
sudo chmod a+rwx /byoda
cd byoda-python
source tools/set_env.sh
curl -s -X GET --cacert $ROOT_CA --cert $MEMBER_ADDR_CERT --key $MEMBER_ADDR_KEY --pass $PASSPHRASE \
    --data '{"mentions": ["glynmoody"]}' \
    -H "Content-Type: application/json" \
	https://service.service-$SERVICE_ADDR_ID.byoda.net/api/v1/service/search/asset  | jq .
```

The search API does not return the content but returns the member_id and asset_id so you can request the content from the pod that has stored the content.

## TODO:
The byoda software is currently alpha quality. There are no web UIs or mobile apps yet. curl and 'call-graphql' are currently the only user interface.

The main areas of development are:
- Create a web user interface for the address book service
- Implementing the 'network:+n' construct (with n>1) for the access permissions in the JSON Schema to allow people in your network to query your GraphQL APIs.
- Improve the support for complex data structures in the data contract
- create algorithms that you can run to collect data from your pod, the pods of your network and APIs hosted by the service to generate a feed of content for you.

