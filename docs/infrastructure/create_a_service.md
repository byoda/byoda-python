# Creating a service

There are 4 phases/steps to set up a service

## 1: create the service contract

The service contract is a hybrid JSON / JSON-Schema file. At the top level, there is a JSON object that must have the following keys with simple (ie. not objects or lists) values (see [byoda-python/byoda/models/schema.py](https://github.com/StevenHessing/byoda-python/blob/users/stevenh/add_membership/byoda/models/schema.py)):

```
    service_id: int     # Must be unique
    version: int        # must be higher than previous version of schema
    name: str           # Name of the service
    description: str    # Short description of the service
    owner: str          # Your name or the name of your company owning the service
    website: str        # Website for the service
    supportemail: str   # Email address for contacting you for support
```

In addition, there are the 'signatures' and 'jsonschema' keys. Use the empty object value '{}' for the 'signatures' key. We'll add the signatures later and we'll discuss the 'jsonschema' key below.

The service_id must be an integer. Here are the guidelines to the values:
- 0: reserved for the 'private' service that each network must support
- 1: reserved for the 'directory' service that each network must support
- 1 < value < 1024 : do not use, only standard services that each network must support can use these values
- 1024 < value < 2**32-2**16 : service contracts with these values are subject to manual review
- 2**32-2**16 < value < 2**32: These are values for testing services. Any registration of a service with a service_id not currently in use will be approved. Any service registered with one of these values is subject to deletion at any given time (for example first day of each month) so you may have to re-register your service periodically. There is no guarantee that you will be able to re-use your previous service ID

Each service must have a unique Service ID. You can see what services are currently using what Service IDs you can call the network/nervices API, ie.

```
export BYODA_NETWORK=byoda.net
curl https://dir.${BYODA_NETWORK}/api/v1/network/services
```
Note that this API uses pagination so you may have to use the 'skip=<n>' query parameter to iterate over all services

The value for the 'jsonschema' key must be a valid [JSON-Schema](https://json-schema.org) document. Use the existing byoda-python/services/{private,directory}.json files as starting points. The support and extensions for various constructs in the JSON schema and how to translate those constructs to GraphQL queries and processing those queries is the main area of development for BYODA so expect ongoing changes on what is supported in the JSON Schema.

## 2: Create the secrets for a service

Each service has the following secrets:
- ServiceCA: signed by the Network Services CA, which s operated by the network
- Service: The TLS secret used both for the web server and as client TLS cert for outbound connections
- AppsCA: signed by the Service CA, used to sign secrets for 'apps' supported by the service. (but 'Apps' are currently not yet implemented/supported)
- MembersCA: signed by the Service CA, signs Certificate Signing Requests (CSRs) from pods that want to join the service using the POST /api/v1/service/member API
- ServiceData: Signed by the Service CA. This is the secret used to sign documents, such as the service schema/data contract so that others can verify its authenticity

We create the service secrets using the 'tools/create_service_secrets.py' script. It is best practice to create and store the ServiceCA secret on an off-line server. _*Make sure to carefully review the output of the script as it contains the password needed to decrypt the private key for the Service CA*_. You need to save this password in a password manager and you may need it in the future when your service secrets expire and need to be re-generated!

```
export BYODA_HOME=/opt/byoda
export BYODA_DOMAIN=byoda.net


export SERVICE_CONTRACT=<path-to-your-service-file>

# Here we update the 'service_id' in the service schema to match a newly generated random service ID
export SERVICE_ID=$( python3 -c 'import random; print(pow(2,32)-random.randint(1,pow(2,16)))')
sudo apt install moreutils      # for the 'sponge' tool that we use on the next line
 jq --arg service_id "$SERVICE_ID" '.service_id = $service_id' ${SERVICE_CONTRACT} | sponge ${SERVICE_CONTRACT}

export SERVICE_DIR="${BYODA_HOME}/service-${SERVICE_ID}"
sudo mkdir -p ${SERVICE_DIR}
sudo chown -R ${USER}:${USER} ${BYODA_HOME}
cd ${BYODA_HOME}
git clone https://github.com/StevenHessing/byoda-python
cd byoda-python
export PYTHONPATH=${PYTHONPATH}:$(pwd)
sudo pip3 install passgen
PASSWORD=$(passgen -n 1 -l 48)
echo "Passwords for service secrets except the Service CA: ${PASSWORD}
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

## 3: Signing your schema

There are two signatures for a schema: the ServiceData secret provides the 'service' signature and the NetworkServicesCA provides the 'network' signature.

As you just created the ServiceData secret in step #2, you can generate the service signature but you'll have to ask the directory server of the network to provide the network signature by calling the PATCH /api/v1/network/service API. Both steps are implemented by the '[tools/sign_data_contract.py](https://github.com/StevenHessing/byoda-python/blob/master/tools/sign_data_contract.py)' script.

```
export BYODA_HOME=/opt/byoda
export BYODA_DOMAIN=byoda.net

export SERVICE_CONTRACT=<path-to-your-service-file>

export SERVICE_ID=$(jq -r .service_id ${SERVICE_CONTRACT})
export SERVICE_DIR="${BYODA_HOME}/service-${SERVICE_ID}"

cd ${BYODA_HOME}/byoda-python
export PYTHONPATH=${PYTHONPATH}:$(pwd)
tools/sign_data_contract.py --debug --contract ${SERVICE_CONTRACT} --network ${BYODA_DOMAIN} --root-directory ${SERVICE_DIR} --password=${PASSWORD}
