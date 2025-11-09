# Creating a service

There are 4 phases/steps to set up a service

## 1: Install required software

Install angie as reverse proxy as per the [instructions of F5/Angie](https://docs.angie.com/angie/admin-guide/installing-angie/installing-angie-open-source/)

Then install the angie.conf file

```bash
sudo cp docs/files/angie-service.conf /etc/angie/angie.conf
sudo angie -s reload
```

Services typically need to store data about their members. With Byoda, services are not allowed to persist data (with just a very few exceptions) about their members but are allowed to cache that data. The reference implementation of the service server uses Redis to temporarily store information as Redis can automatically remove expired data.

To install Redis, first install docker as per the [Docker instructions](https://docs.docker.com/engine/install/ubuntu/) and then launch the redis container.

```bash
sudo mkdir -p /opt/redis/data
sudo mkdir -p /opt/redis/etc
sudo docker run -d --restart unless-stopped \
    -p 6379:6379 \
    -v /opt/redis/data:/data \
    -v /opt/redis/etc/redis-stack.conf:/redis-stack.conf \
    --name redis redis/redis-stack-server:latest
```

To also set up the Prometheus exporter for redis, you can use the following command:

```bash
export PRIVATE_IP=$(hostname -I | awk '{print $1}') && echo $PRIVATE_IP
export REDIS_ADDR='redis://${PRIVATE_IP}:6379'
export REDIS_EXPORTER_CHECK_SINGLE_KEYS=lists:all_assets
docker run -d --restart unless-stopped --name redis_exporter --network host quay.io/oliver006/redis_exporter
```


## 2: Pick a value for the service ID

Each service must have a unique integer value for the SERVICE_ID. Here are the rules to the values:

- 0: reserved for the 'private' service that each network must support
- 1 <= value < 16384 : do not use, only standard services that each network must support can use these values
- 16384 <= value < 2**32-2**16 : service contracts with these values are subject to both automated and manual review (note, manual review is not yet implemented).
- 2**32-2**16 <= value < 2**32: These are values for testing services. Any registration of a service with a service_id not currently in use will be approved after an automated review. Any service registered with one of these values is subject to deletion at any given time (for example first day of each month) so you may have to re-register your service periodically. Clients must explicitly acknowledge that they want to become member of a service with a service_id in this range before the membership is established. Any assigned service_ids from this range are ephemeral. Periodically, all allocations from this range are reset. The directory server will wipe any DNS records and certs for services using this range. You will need to resubmit the JSON file and there is no guarantee you can re-use the same service_id. Clients will have to re-join your service with the new service_id

You can see what services are currently using what Service IDs you can call the network/nervices API, ie.

```bash
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

We do not support the full specification of JSON Schema for the translation to the Data API. The JSON file for the addressbook schema can be used as a starting point for creating a new schema. Specifically, we know of the following support:

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
- the name of the object must not start with '#', '_', 'byoda', or 'BYODA'

If the type is "object" then it must have a key "properties" with as value an object with the keys:

- description: What the data stored in this property is used for
- #accesscontrol: see below for more information
- type: must be a scalar, (ie. "string" or "number") or an array
- format: any value for this key is used for data validation but is not translated into the Data API

IF the type is "array" then the following keys are supported:

- description: Required field. What the data stored in this property is used for
- #accesscontrol: Optional field. See below for more information
- items: must be an object with a key with one of these two values:
  - type: must be "string" or "integer"
  - $ref: a string that must match one of the classes defined under $defs (see below)

A data structure under $defs must have the following keys:

- $id: string with "/schemas/<class-name>"
- $schema: Must be set to "https://json-schema.org/draft-07/schema#"
- description: What the data stored in this class is used for
- type: must be "object"
- #properties: optional field with a list of strings. Each string must be one of the supported values:
  - primary_key: use this field to match nested objects to this object. Only one field in an object can have this property set
  - index: maintain an index for this field
  - counter: maintain counters for this field. Only supported for fields of type UUID and string
- properties: must be a dict with as keys the different properties of the class. Each property must have keys:
  - description: What the data stored in this property is used for
  - type: must be a scalar, ie. "string" or "number" or an array.
  - format: any value for this key is used for data validation but is not translated into the Data API

There are some data structures that the BYODA pod uses for various purposes. These data structures are required to be present in your service schema with the corresponding fields and data types.
Several data structures are required to be defined directly under the root of the JSON Schema. These can be copied
from the addressbook.json service contract to your contract.

- member, with definitions:
  - "#access control": {"member": ["read"]}
  - "properties" dict k/vs:
    - "joined": { "format": "date-time", "type": "string"}
    - "member_id": {"type": "string"}
    - "supported_versions": {"type": "string"} # command separated list of supported schema versions
    - "auto_upgrade": {"type": "boolean"} # if true, the plan is for the pod to automatically upgrade the schema of the member to the latest version supported by the service
- network_links of type array using the /schemas/network_link as reference
- datalogs of type array using the /schemas/memberlog as reference
- incoming_claims: claims from other people that you haven't verified yet
- verified_claims: claims from other people that you have verified

The pod maintains counters for each field of an object that has the 'counter' property defined. For each array of objects there is an '<array-class-name>_counter' WebSocket API. When called without filters, the API returns the number of objects in the array when that number increases or decreases. When you specify one or more filters, the counters matching those filters are returned. This enables the counters API to return only objects for example in the network_links table if an object was added with 'relation' == 'friend'. When objects are deleted from an array, the counters for fields in that array are only decreased if the call to the delete API included values for all fields that have the 'counter' property defined. To mitigate API invocations where these values are not specified, the pod_worker process will periodically update counters based on the data stored for the array.

If a scalar field is no longer required then it may be defined with ```"#obsolete": true```. This will avoid the dataclass for it to be created so no logic will use it. The field will not be deleted from the datastores of pods but it is no longer possible to use Data APIs to query or update it. It is not possible to remove a previously-defined field, you have to specify the ```"#obsolete": true``` property instead. Care should be taken with this option as clients using an older version of the schema will create queries specifying obsolete field, which is no longer known by the clients running the new version, causing those queries to fail.

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
  - cache (int: seconds or string with "4h", "600s", "1d" etc., defaults to 1 week, which is 604800 seconds): how long may the requesting entity cache the data
- update, no specifiers
- delete: delete the records matching the value of the specified filters
- append: add an entry to an array
- persist: allow the client to persist this data. This action must only be used for data that the service  needs to reach out to members when there is a problem with the service or with someones membership of the service, ie. the email address and the member_id of the membership. In addition, pods and services are allowed to store the member_id of a member of a service
- search: special case to allow services to provide a search function

The access controls can only be defined for the 'properties' defined for the 'jsonschema' in the service contract and not for the data structures defined under the '$defs' section

### Listen relations
The service schema may have an array 'listen_relations' at the root level of the schema. The pod uses listen relations to subscribe to updates from other pods using websockets. The pod caches received content in a 'cache-only' data class so that the owner of the pod only needs to connect to their own pod to get content, instead of connecting to many pods. It also ensures that data is immediately available to the owner of the subscribing pod.

Each object in this list must have the following keys:
- class_name (string): the class to subscribe for updates
- relations (list of strings): a pod will subscribe to updates from all pods that our pod has one or more of the specified relations
- destination_class (string): the class on the local pod where updates will be stored. This class must have at least contain all the same field definitions as the class specified by the 'class_name' key
- feed_class (optional string): Each pod runs a worker to generate feeds. This worker will listen for updates to the
class specified by the 'destination_class' and runs some sort of algorithmic analytics to determine which data should be copied to the (cache-only) feed_class.

## 4: Create the secrets for a service

Each service has the following secrets:

- ServiceCA: signed by the Network Services CA, which s operated by the network
- Service: The TLS secret used both for the web server and as client TLS cert for outbound connections
- AppsCA: signed by the Service CA, used to sign secrets for 'apps' supported by the service. (but 'Apps' are currently not yet implemented/supported)
- MembersCA: signed by the Service CA, signs Certificate Signing Requests (CSRs) from pods that want to join the service using the POST /api/v1/service/member API
- ServiceData: Signed by the Service CA. This is the secret used to sign documents, such as the service schema/data contract so that others can verify its authenticity

We create the service secrets using the 'tools/create_service_secrets.py' script. It is best practice to create and store the ServiceCA secret on an off-line server. _Make sure to carefully review the output of the script as it contains the password needed to decrypt the private key for the Service CA_. You need to save this password in a password manager and you may need it in the future when your service secrets expire and they need to be re-generated!

```bash
export BYODA_HOME=/opt/byoda
export BYODA_DOMAIN=byoda.net

export SERVICE_CONTRACT=<service contract file>   # should be only the filename, no path included

export SERVICE_ID=$(python3 -c 'import random; print(pow(2,32)-random.randint(1,pow(2,16)))') && echo ${SERVICE_ID}

# Here we update the 'service_id' in the service schema to match a newly generated random service ID
sudo apt install moreutils      # for the 'sponge' tool that we use on the next line
jq -r --argjson service_id "$SERVICE_ID" '.service_id = $service_id' ${BYODA_HOME}/${SERVICE_CONTRACT} | sponge ${BYODA_HOME}/${SERVICE_CONTRACT}

export SERVICE_DIR="${BYODA_HOME}/service-${SERVICE_ID}"
sudo mkdir -p ${SERVICE_DIR}
sudo chown -R ${USER}:${USER} ${BYODA_HOME}
mv ${BYODA_HOME}/$SERVICE_CONTRACT ${SERVICE_DIR}

cd ${BYODA_HOME}
git clone https://github.com/byoda/byoda-python
cd byoda-python
export PYTHONPATH=${PYTHONPATH}:${BYODA_HOME}/byoda-python
sudo pip3 install passgen
PASSWORD=$(passgen -n 1 -l 48)
echo "Passwords for service secrets except the Service CA: ${PASSWORD}"
pipenv run tools/create_service_secrets.py --debug --schema ${SERVICE_CONTRACT} --network ${BYODA_DOMAIN} --root-directory ${SERVICE_DIR} --password ${PASSWORD} 2>&1 | tee /tmp/service.log
```

Make sure you retrieved the generated secret to protect the private key of the Service CA as described in the previous alinea. Look for the line with '!!' in it. Delete the service log file after you have extracted and persisted the secret protecting the private key.

Services use the 'Service CA' as root certificate, eventhough that cert has been signed by the Network Services CA, which is signed by the Network Root cert. To use the Service CA cert as root, openssl needs the CA file to fully resolve so we need to combine the Service CA cert with the Network Services CA cert and the Network Root CA cert in a single file

```bash
cat ${SERVICE_DIR}/network-${BYODA_DOMAIN}/{services/service-${SERVICE_ID}/network-${BYODA_DOMAIN}-service-${SERVICE_ID}-ca-cert.pem,network-${BYODA_DOMAIN}-root-ca-cert.pem} > ${SERVICE_DIR}/network-${BYODA_DOMAIN}/services/service-${SERVICE_ID}/network-${BYODA_DOMAIN}-service-${SERVICE_ID}-ca-certchain.pem
```

Make sure you securely store the passwords for the ServiceCA and the password for the other secrets, for example in a password manager.
Now you can copy all secrets except the private key of the ServiceCA to the server you want to host the service.

```bash
SERVER_IP=<IP address of your server>

ssh ${SERVER_IP} "sudo mkdir -p ${SERVICE_DIR}; sudo chown -R ${USER}:${USER} ${BYODA_HOME}"
cd ${BYODA_HOME}
scp -r * ${SERVER_IP}:${BYODA_HOME}
ssh ${SERVER_IP} "rm ${SERVICE_DIR}/private/network-${BYODA_NETWORK}-service-${SERVICE_ID}-service-ca.key
```

## 5: Signing your schema

There are two signatures for a schema: the ServiceData secret you have just created, provides the 'service' signature and the NetworkServicesCA provides the 'network' signature.

As you just created the ServiceData secret in step #2, you can generate the service signature but you'll have to ask the directory server of the network to provide the network signature by calling the PATCH /api/v1/network/service API. Both steps are implemented by the '[tools/sign_data_contract.py](https://github.com/byoda/byoda-python/blob/master/tools/sign_data_contract.py)' script. Before you can run the tool, you have to create a config.yml, that later will also be used when you start the server. Copy the config-sample.yml file in the byoda-python directory to config.yml, remove the 'dirserver' block and edit the configuration as appropriate.

```bash
export BYODA_HOME=/opt/byoda
export BYODA_DOMAIN=byoda.net

export SERVICE_CONTRACT=addressbook.json

export SERVICE_ID=$(jq -r .service_id ${BYODA_HOME}/${SERVICE_CONTRACT}); echo "Service ID ${SERVICE_ID}"
export SERVICE_DIR="${BYODA_HOME}/service-${SERVICE_ID}"

if [ ! -f $BYODA_HOME/byoda-python/config.yml ]; then
    cat config-sample.yml | \
        sed "s|SERVICE_ID|${SERVICE_ID}|" | \
        sed "s|BYODA_DOMAIN|${BYODA_DOMAIN}|" | \
        sed "s|PASSWORD|${PASSWORD}|" | \
        sed "s|BYODA_HOME|${BYODA_HOME}|" > config.yml
fi

cd ${BYODA_HOME}
mkdir -p ${SERVICE_DIR}
sudo mv ${BYODA_HOME}/${SERVICE_CONTRACT} ${SERVICE_DIR}
sudo chown $USER:$USER  /var/tmp/service-${SERVICE_ID}.key

cd ${BYODA_HOME}/byoda-python
export PYTHONPATH=${PYTHONPATH}:${BYODA_HOME}/byoda-python
pipenv run tools/sign_data_contract.py --debug --contract ${SERVICE_CONTRACT}

# Set file ownership of the unencrypted private key to the user/group used
# by angie so it can read the private key
sudo chown www-data:www-data /var/tmp/service-${SERVICE_ID}.key
```

## 6: Get the service up and running

The service server can be run as a container

```bash
mkdir -p /var/log/byoda
docker run -d   --name byoda-service \
    --restart=unless-stopped \
    -p 8010:8000 \
    -e "LOGLEVEL=DEBUG" \
    -e "WORKERS=2" \
    -e "SERVER_NAME=service-${SERVICE_ID}.${BYODA_DOMAIN}" \
    -v /var/log/byoda:/var/log/byoda \
    -v ${SERVICE_DIR}:${SERVICE_DIR} \
    -v ${BYODA_HOME}/byoda-python/config.yml:${BYODA_HOME}/byoda-python/config.yml \
    byoda/byoda-service:latest

ANGIE_USER=www-data
mkdir -p ${SERVICE_DIR}/network-${BYODA_DOMAIN}/account-pod
sudo chown -R ${ANGIE_USER}:${ANGIE_USER} ${SERVICE_DIR}/network-${BYODA_DOMAIN}/{services,account-pod}
if [ -f /var/tmp/service-${SERVICE_ID}.key ]; then
    sudo chown ${ANGIE_USER}:${ANGIE_USER} /var/tmp/service-${SERVICE_ID}.key
fi
```

The service daemon will create an Angie configuration file under /etc/angie/conf.d
and make angie load that new configuration.

To test the service certificate signed by the root CA of the network, you can use openssl and/or curl:

```bash
openssl s_client -connect service.service-0.byoda.net:443 -CAfile root-ca.pem

curl  https://service.service-0.byoda.net/network-byoda.net-service-0-data-cert.pem -o network-byoda.net-service-0-data-cert.pem --cacert root-ca.pem
```

Now we need to install the service worker. The service worker collects information from the person object of members of the service and stores it in Redis. The service uses this data to host an API that allows you to find people based on their email address

```bash
mkdir -p /var/log/byoda
docker run -d   --name byoda-serviceworker \
    --restart=unless-stopped \
    -e "LOGLEVEL=DEBUG" \
    -v /var/log/byoda:/var/log/byoda \
    -v ${SERVICE_DIR}:${SERVICE_DIR} \
    byoda/byoda-serviceworker:latest
```

### Developing the service

The reference svcserver, the updates-worker and the refresh-worker implement a pattern where the svcserver writes a member UUID to a Redis key whenever a pod registers the membership with the svcserver. The Redis key has a list as its value. The updates worker periodically takes a member UUID from the head of the list and pushes it to the back of the list. The updates-worker and refresh-worker can then query data from the pod of that member and store any data listed as cachable in the service contract in Redis
