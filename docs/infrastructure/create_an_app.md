# Create an app

To run an 'app', you need to have:
1: a DNS name for the application server
2 an App cert/key
3: run the application server.

## DNS name

You can use any FQDN you want, but it must be resolvable by clients.

## App cert/key

To create an app cert/key, first set these environment variables:

```bash
export NETWORK=<network_name>           # ie. byoda.net
export SERVICE_ID=<service_id>          # ie. 4294929430
export FQDN=<dns_name>                  # ie modtest.byoda.io
export BYODA_PASSWORD=<password>        # some super secure password
```

and now run:

```bash
git clone https://github.com/byoda/byoda-python
cd byoda-python
export PYTHONPATH=${PYTHONPATH}:.
pipenv install
pipenv shell
tools/create_csr.py \
    --network ${NETWORK} \
    --service_id ${SERVICE_ID} \
    --type app \
    --fqdn ${FQDN} \
    --out_dir .
```
