# Creating a service

There are 4 phases/steps to set up a service

## 1: Install required software
Install nginx as reverse proxy as per the [instructions of F5/Nginx](https://docs.nginx.com/nginx/admin-guide/installing-nginx/installing-nginx-open-source/)

Then install the nginx.conf file
```
sudo cp docs/files/nginx-service.conf /etc/nginx/nginx.conf
sudo nginx -s reload
```

Services typically need to store data about their members. With Byoda, services are not allowed to persist data (with just a very few exceptions) about their members but are allowed to cache that data. The reference implementation of the service server uses Redis to temporarily store information as Redis can automatically remove expired data.

To install Redis, first install docker as per the [Docker instructions](https://docs.docker.com/engine/install/ubuntu/) and then launch the redis container.
```
sudo mkdir -p /opt/redis/config
sudo docker run -d --restart unless-stopped \
    -p 6379:6379 \
    -v /opt/redis/config:/usr/local/etc/redis \
    --name redis redis:latest
```

You can review the configuration in /opt/redis/config/redis.conf for any changes that may be needed

## 2: Pick a value for the service ID

Each service must have a unique integer value for the SERVICE_ID. Here are the rules to the values:
- 0: reserved for the 'private' service that each network must support
- 1 <= value < 16384 : do not use, only standard services that each network must support can use these values
- 16384 <= value < 2**32-2**16 : service contracts with these values are subject to both automated and manual review (note, manual review is not yet implemented).
- 2**32-2**16 <= value < 2**32: These are values for testing services. Any registration of a service with a service_id not currently in use will be approved after an automated review. Any service registered with one of these values is subject to deletion at any given time (for example first day of each month) so you may have to re-register your service periodically. Clients must explicitly acknowledge that they want to become member of a service with a service_id in this range before the membership is established. Any assigned service_ids from this range are ephemeral. Periodically, all allocations from this range are reset. The directory server will wipe any DNS records and certs for services using this range. You will need to resubmit the JSON file and there is no guarantee you can re-use the same service_id. Clients will have to re-join your service with the new service_id

You can see what services are currently using what Service IDs you can call the network/nervices API, ie.

```
export BYODA_NETWORK=byoda.net
curl https://dir.${BYODA_NETWORK}/api/v1/network/services
```
Note that this API uses pagination so you may have to use the 'skip=<n>' query parameter to iterate over all services

## 3: Developing the schema

### The JSON file
The schema is a JSON file with a JSON Schema embedded. We have not yet published a JSON Schema for this JSON file.

The JSON file at the top-level must have the following keys:
|--------------|--------|---    --------------------------------------------------------------------|
| description  | string     | A description of your service                                         |
| name         | string     | The name of your service                                              |
| owner        | string     | Your name of the name of the company you create the service for       |
| supportemail | string     | Email address where a person can request support for a service        |
| website      | string     | The URL to your website                                               |
| service_id   | integer    | the service ID for your service. As discussed in section #2           |
| version      | integer    | the version of the schema. See below on versioning                    |
| signatures   | object     | a JSON object, see section 5 on the signing of the JSON file          |
| jsonschema   | jsonschema | the JSON Schema for the data for the service                          |
|--------------|------------|-----------------------------------------------------------------------|

We use the python [fastjsonschema](https://horejsek.github.io/python-fastjsonschema/) module for validating data against the JSON Schema, which states support for JSON Schema draft 4, 5, and 7.
We do not support the full specification of JSON Schema for the translation to the GraphQL API. The JSON file for the addressbook schema can be used as a starting point for creating a new schema. Specifically, we know
of the following support:
- At the root level of the schema, we support the following keys:
  - $id: must be a string with value: "https://<service-UUID>.services.byoda.net/service/<name of your service>. The name of your service must match the "name" field at the top level of the schema. The service-UUID must match the UUID assigned to your service.
  - $schema: Must be set to "https://json-schema.org/draft-07/schema#"
  - $defs: one or more definitions of a data object, see below
  - title: must match the "name" field at the top level of the schema
  - description: must match the "description" field at the top level of the schema
  - type: must be "object"
  - properties: see below

### Versioning
The integer value for the version key the JSON file must be 1 or higher. When you submit the JSON file to the directory server, the version must be increased by 1 from the previously successfully submitted JSON file. Submitting a JSON file to get the network signature for the schema with the version unchanged from a previous successful request will fail.

### Data objects
The keys of properties directly under the JSON Schema (so not under $defs) must be the name of classes and the keys for each class must be:
  - description: What the data stored in this class is used for
  - type: must be "object" or "array"
  - #accesscontrol: a dict with the specification of who has access to the data stored in instances of the class. See the section on access control below for more information

If the type is "object" then it must have a key "properties with as value an object with the keys:
  - description: What the data stored in this property is used for
  - #accesscontrol: see below for more information
  - type: must be a scalar, (ie. "string" or "number") or an array
  - format: any value for this key is used for data validation but is not translated into the GraphQL API

IF the type is "array" then the following keys are required:
  - description: What the data stored in this property is used for
  - #accesscontrol: see below for more information
  - items: must be an object with a key with one of these two values:
    - type: must be "string" or "integer"
    - $ref: a string that must match one of the classes defined under $defs (see below)

A data structure under $defs must have the following keys:
- $id: string with "/schemas/<class-name>"
- $schema: Must be set to "https://json-schema.org/draft-07/schema#"
- description: What the data stored in this class is used for
- type: must be "object"
- properties: must be a dict with as keys the different properties of the class. Each property must have keys:
  - description: What the data stored in this property is used for
  - type: must be a scalar, ie. "string" or "number" or an array.
  - format: any value for this key is used for data validation but is not translated into the GraphQL API

Several data structures are required to be defined directly under the root of the JSON Schema. These can be copied
from the addressbook.json service contract to your contract.
- member, with definitions:
    - "#access control": {"member": ["read"]}
    - "properties" dict k/vs:
      - "joined": { "format": "date-time", "type": "string"}
      - "member_id": {"type": "string"}
- network_links of type array using the /schemas/network_link as reference
- memberlogs of type array using the /schemas/memberlog as reference

### Data Access control
The Pod controls access to the data for the services stored in the Pod based on access controls that
are defined in the service contract for each of the services. After evaluating the data requested by a client
against these access controls, the Pod may return no data or some or all of the requested data.

The access controls consist of one or more defined entities, with for each entity a list of actions that are
permitted. Each of the actions may support some specifiers that provide additional info on data may be used. The supported entities are:
- member: The membership in the Pod of the service, or, with other words, you; the owner of the pod
- service: The person or organization hosting the service
- network: someone that you have a network relation with. This entity supports two specifiers:
  - distance (integer, n>=1, default=1): some other member who you have a network path in your social graph with, with a maximum distance of 'n'
  - relation (string with regular expression, defaults to None): the relation with the members in your social graph must match this regular expression. If not specified, all relations are permitted access
- any_member: Any person who has joined the service
- anonymous: Anyone, regardless whether or not they provided credentials to authenticate their data request

The following actions are supported:
- read with specifier:
  - cache (int: seconds or string with "4h", "600s", "1d" etc., defaults to 14400 seconds): how long may the requesting entity cache the data
- update, no specifiers
- delete: delete the records matching the value of the specified filters
- append: add an entry to an array
- persist: allow the client to persist this data. This action is only supported for the 'service' entity. This action must only be used for data that the service needs to reach out to members when there is a problem with the service or with someones membership of the service, ie. the email address and the member_id of the membership.
- search: special case to allow services to provide a search function

The access controls can only be defined for the 'properties' defined for the 'jsonschema' in the service contract and not for the data structures defined under the '$defs' section

## 4: Create the secrets for a service

Each service has the following secrets:
- ServiceCA: signed by the Network Services CA, which s operated by the network
- Service: The TLS secret used both for the web server and as client TLS cert for outbound connections
- AppsCA: signed by the Service CA, used to sign secrets for 'apps' supported by the service. (but 'Apps' are currently not yet implemented/supported)
- MembersCA: signed by the Service CA, signs Certificate Signing Requests (CSRs) from pods that want to join the service using the POST /api/v1/service/member API
- ServiceData: Signed by the Service CA. This is the secret used to sign documents, such as the service schema/data contract so that others can verify its authenticity

We create the service secrets using the 'tools/create_service_secrets.py' script. It is best practice to create and store the ServiceCA secret on an off-line server. _*Make sure to carefully review the output of the script as it contains the password needed to decrypt the private key for the Service CA*_. You need to save this password in a password manager and you may need it in the future when your service secrets expire and they need to be re-generated!

```
export BYODA_HOME=/opt/byoda
export BYODA_DOMAIN=byoda.net

export SERVICE_CONTRACT=<service contract file>   # should be only the filename, no path included

export SERVICE_ID=$(python3 -c 'import random; print(pow(2,32)-random.randint(1,pow(2,16)))')

# Here we update the 'service_id' in the service schema to match a newly generated random service ID
sudo apt install moreutils      # for the 'sponge' tool that we use on the next line
jq -r --argjson service_id "$SERVICE_ID" '.service_id = $service_id' ${BYODA_HOME}/${SERVICE_CONTRACT} | sponge ${BYODA_HOME}/${SERVICE_CONTRACT}

export SERVICE_DIR="${BYODA_HOME}/service-${SERVICE_ID}"
sudo mkdir -p ${SERVICE_DIR}
sudo chown -R ${USER}:${USER} ${BYODA_HOME}
mv ${BYODA_HOME}/$SERVICE_CONTRACT ${SERVICE_DIR}

cd ${BYODA_HOME}
git clone https://github.com/StevenHessing/byoda-python
cd byoda-python
export PYTHONPATH=${PYTHONPATH}:${BYODA_HOME}/byoda-python
sudo pip3 install passgen
PASSWORD=$(passgen -n 1 -l 48)
echo "Passwords for service secrets except the Service CA: ${PASSWORD}"
tools/create_service_secrets.py --debug --schema ${SERVICE_CONTRACT} --network ${BYODA_DOMAIN} --root-directory ${SERVICE_DIR} --password ${PASSWORD} 2>&1 | tee /tmp/service.log

```

Make sure you securely store the passwords for the ServiceCA and the password for the other secrets, for example in a password manager.
Now you can copy all secrets except the private key of the ServiceCA to the server you want to host the service.
```
SERVER_IP=<IP address of your server>

ssh ${SERVER_IP} "sudo mkdir -p ${SERVICE_DIR}; sudo chown -R ${USER}:${USER} ${BYODA_HOME}"
cd ${BYODA_HOME}
scp -r * ${SERVER_IP}:${BYODA_HOME}
ssh ${SERVER_IP} "rm ${SERVICE_DIR}/private/network-${BYODA_NETWORK}-service-${SERVICE_ID}-service-ca.key
```

## 5: Signing your schema

There are two signatures for a schema: the ServiceData secret provides the 'service' signature and the NetworkServicesCA provides the 'network' signature.

As you just created the ServiceData secret in step #2, you can generate the service signature but you'll have to ask the directory server of the network to provide the network signature by calling the PATCH /api/v1/network/service API. Both steps are implemented by the '[tools/sign_data_contract.py](https://github.com/StevenHessing/byoda-python/blob/master/tools/sign_data_contract.py)' script. Before you can run the tool, you have to create a config.yml, that later will also be used when you start the server. Copy the config-sample.yml file in the byoda-python directory to config.yml, remove the 'dirserver' block and edit the configuration as appropriate.

```
export BYODA_HOME=/opt/byoda
export BYODA_DOMAIN=byoda.net

export SERVICE_CONTRACT=addressbook.json

export SERVICE_ID=$(jq -r .service_id ${BYODA_HOME}/${SERVICE_CONTRACT})
export SERVICE_DIR="${BYODA_HOME}/service-${SERVICE_ID}"

if [ ! -f $BYODA_HOME/byoda-python/config.yml ]; then
    cat config-sample.yml | \
        sed "s|SERVICE_ID|${SERVICE_ID}|" | \
        sed "s|BYODA_DOMAIN|${BYODA_DOMAIN}|" | \
        sed "s|PASSWORD|${PASSWORD}|" | \
        sed "s|BYODA_HOME|${BYODA_HOME}|" > config.yml
fi

mkdir -p ${SERVICE_DIR}
sudo cp ${BYODA_HOME}/${SERVICE_CONTRACT} ${SERVICE_DIR}
# Delete any existing unencrypted private key for the service
sudo rm -f /tmp/service-${SERVICE_ID}.key

cd ${BYODA_HOME}/byoda-python
export PYTHONPATH=${PYTHONPATH}:${BYODA_HOME}/byoda-python
tools/sign_data_contract.py --debug --contract ${SERVICE_CONTRACT}

## 6: Get the service up and running
These instructions are assuming you've installed the service server on an distribution that uses systemd(8), ie. Debian, Ubuntu

```
NGINX_USER=www-data
mkdir -p ${SERVICE_DIR}/network-${BYODA_DOMAIN}/account-pod
sudo chown -R ${NGINX_USER}:${NGINX_USER} ${SERVICE_DIR}/network-${BYODA_DOMAIN}/{services,account-pod}
if [ -f /tmp/service-${SERVICE_ID}.key ]; then
    sudo chown ${NGINX_USER}:${NGINX_USER} /tmp/service-${SERVICE_ID}.key
fi

if [ ! -f /etc/default/svcserver-${SERVICE_ID} ]; then
    sudo cp docs/files/svcserver.default /etc/default/svcserver-${SERVICE_ID}
    sed -i "s|SERVICE_ID|$SERVICE_ID|" /etc/default/svcserver-${SERVICE_ID}
fi

if [ ! -f /etc/systemd/system/svcserver-${SERVICE_ID}.service ]; then
    sudo cp docs/files/svcserver-systemd.service /etc/systemd/system/svcserver-${SERVICE_ID}.service
    sed -i "s|SERVICE_ID|$SERVICE_ID|" /etc/systemd/system/svcserver-${SERVICE_ID}.service
fi

sudo systemctl daemon-reload
sudo systemctl start svcserver-${SERVICE_ID}
sleep 5
sudo systemctl status svcserver-${SERVICE_ID}
sudo systemctl enable svcserver-${SERVICE_ID}
```

The service daemon will create an Nginx configuration file under /etc/nginx/conf.d
and make nginx load that new configuration.

To test the service certificate signed by the root CA of the network, you can use openssl and/or curl:
```
openssl s_client -connect service.service-0.byoda.net:443 -CAfile root-ca.pem

curl  https://service.service-0.byoda.net/network-byoda.net-service-0-data-cert.pem -o network-byoda.net-service-0-data-cert.pem --cacert root-ca.pem
```

### Developing the service
The reference svcserver and the svcworker implement a pattern where the svcserver writes a member UUID to a Redis key whenever a pod registers the membership with the svcserver. The Redis key has a list as its value. The svcworker periodically takes a member UUID from the head of the list and pushes it to the back of the list. The svcworker can then query data from the pod of that member and store any data listed as cachable in the service contract in Redis
