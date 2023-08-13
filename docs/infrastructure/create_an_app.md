# Create an application

Byoda application will be used by third parties to deliver various
services in the eco-system of a service. The first implementation of an
application is the moderation of content. Going forward, additional
services wil become available.

To run an 'application', you need to:
1: have a DNS name for the application server
2: have an App cert/key, signed by the Apps CA of the target service
3: run the application server.

## DNS name

You can use any FQDN you want, but it must be resolvable by clients.

## Application cert/key

To create an application cert/key, first set these environment variables:

```bash
export NETWORK=<network_name>           # ie. byoda.net
export SERVICE_ID=<service_id>          # ie. 4294929430
export FQDN=<dns_name>                  # ie modtest.byoda.io
export BYODA_PASSWORD=<password>        # some super secure password
```

With the create_csr tool, you will create a Certificate Signing Request
and submit it for signing to the service.

```bash
apt-get install --yes uuid
APP_ID=$(uuid -v 4)
git clone https://github.com/byoda/byoda-python
cd byoda-python
export PYTHONPATH=${PYTHONPATH}:.
pipenv install
pipenv run tools/create_csr.py \
    --network ${NETWORK} \
    --service_id ${SERVICE_ID} \
    --type app \
    --app-id ${APP_ID} \
    --fqdn ${FQDN} \
    --out_dir .
```

Now you'll need to reach out to the owner of the service, tell them that you have
submitted CSRs for APP_ID ```echo ${APP_ID}``` and explain what kind of
application you would like to run for their service. If they approve, they will
sign the CSRs and send you back the signed certificates.

FYI, the service owner will use the following command to sign the CSR:

```bash
cd $BYODA_GIT_DIR
export BYODA_PASSWORD=<password>        # some super secure password
export PRIVATE_APPS_DIR="${SERVICE_DIR}/private/network-${NETWORK}/service-${SERVICE_ID}/apps"
# First the CSR for the cert for M-TLS
pipenv run tools/sign_csr.py \
    --root-dir ${SERVICE_DIR} \
    --csr-file ${PRIVATE_APPS_DIR}/app-${APP_ID}-csr.pem \
    --type app \
    --out_dir .
# Now the CSR for the data cert
pipenv run tools/sign_csr.py \
    --root-dir ${SERVICE_DIR} \
    --csr-file ${PRIVATE_APPS_DIR}/app-data-${APP_ID}-csr.pem \
    --type app \
    --out_dir .
```

## Run the application server

The application server expects the cert and key to available in a specific
directory structure so let's create that and copy the certs (as received from the service) and private keys (that were created by 'create_csr.py').

```bash
Copy the cert/keys to the correct directory

```bash
export BYODA_HOME=<some-path>
export APP_DIR=<app-dir>         # this is the directory under which appserver will read and save files
export SERVICE_DIR="${BYODA_HOME}\${APP_DIR}"

export KEY_DIR="${SERVICE_DIR}/private/network-${NETWORK}/service-${SERVICE_ID}/apps"
export CERT_DIR="${SERVICE_DIR}/network-${NETWORK}/service-${SERVICE_ID}/apps"
mkdir -p ${KEY_DIR} ${CERT_DIR}

# These are the certs signed by the service owner
cp app-${FQDN}.pem app-data-${FQDN}.pem ${CERT_DIR}
cp app-${FQDN}.key app-data-${FQDN}.key ${KEY_DIR}
```

We now create/modify byoda-python/config.yml to point to the correct cert/key files, make sure to set the directories, network, service_id and app_id correctly.

```yaml
application:
  debug: True
  loglevel: INFO
  environment: 'prod'
  network: 'byoda.net'

appserver:
  name: 'modserver'
  root_dir: '/opt/byoda/modtest'
  fqdn: 'modtest.byoda.io'
  claim_request_dir: '/opt/byoda/modtest/www/claim-requests'
  claim_dir: '/opt/byoda/modtest/www/claims/'
  logfile: '/var/log/byoda/modtest.log'
  roles:
    - app
  service_id: <value of the SERVICE_ID environment variable>
  app_id: <value of the APP_ID environment variable>
  private_key_password: '<the password you used with create_csr.py>'
```

Now we create the container for the application server

```bash
export NAME=moderate
export HOSTNAME="${NAME}"
export PORTMAP="-p 8000:8000"

sudo mkdir -p /var/log/byoda ${SERVICE_DIR}/www/claim-requests ${SERVICE_DIR}/www/claims

docker run -d \
    --name byoda-${NAME} \
    --restart=unless-stopped \
    ${PORTMAP} \
    -e "LOGLEVEL=INFO" \
    -e "WORKERS=2" \
    -e "SERVER_NAME=$HOSTNAME.${BYODA_DOMAIN}" \
    -v /var/log/byoda:/var/log/byoda \
    -v ${BYODA_HOME}/${SERVICE_DIR}:${BYODA_HOME}/${SERVICE_DIR} \
    -v ${BYODA_HOME}/byoda-python/config.yml:${BYODA_HOME}/byoda-python/config.yml \
    byoda/byoda-${NAME}:latest
```

After 20-30 seconds, you can check the health status using ```docker ps```
