# Setting up a BYODA network

While it is possible to set up your own BYODA network, it is not recommended. In general I believe the consolidation of various services in a single network is the right model. Still, you might disagree with that or you just might want to set up your own network for testing purposes so here are the instructions on setting up your own network.

A basic BYODA network has the following server roles:
- Postgres server as backend for the PowerDNS server
- A PowerDNS server
- An off-line root CA for the private keys of the network-root-ca of the network
  and the service-ca of the 'directory' service
- A BYODA Directory server hosting the 'network' APIs
- A BYODA Service server for hosting the 'directory' service

The roles can all be co-located on a single server or you can
deploy them to multiple servers for additional resilience and scale

## Set up a domain
You need a domain, we'll use 'somecooldomain.net' as example here. You'll have to register the
domain with a domain registrar (like [hover.com](https://www.hover.com/)) and create NS and A records that point to the public IP address of your server.

## Set up a Postgres server

The Postgres server is the storage backend for the PowerDNS DNS server
```

mkdir -p ~/.secrets
chmod 700 ~/.secrets

sudo pip3 install passgen
if [ ! -f ~/.secrets/postgres.password ]; then
  passgen -n 1 >~/.secrets/postgres.password
fi

export POSTGRES_PASSWORD=$(cat ~/.secrets/postgres.password)

sudo mkdir -p /var/lib/postgresql/data
sudo chown -R 999:999 /var/lib/postgresql/

# https://github.com/docker-library/postgres
sudo apt-get -y install docker
sudo docker run -d --restart unless-stopped \
    --publish=5432:5432 \
    -v /var/lib/postgresql/data:/var/lib/postgresql/data \
    -e POSTGRES_PASSWORD=${POSTGRES_PASSWORD} \
    --name postgres \
     postgres:13

sudo apt-get -y install postgresql-client-common
sudo apt-get -y install postgresql-client

echo "*:*:postgres:postgres:${POSTGRES_PASSWORD}" >~/.pgpass
echo "*:*:byodadns:powerdns:${SQL_DNS_PASSWORD}" >>~/.pgpass
chmod 600 ~/.pgpass

export DIRSERVER=$(curl http://ifconfig.co)

if [ ! -f ~/.secrets/sql_powerdns.password ]; then
  passgen -n 1 >~/.secrets/sql_powerdns.password
fi

export SQL_DNS_PASSWORD=$(cat ~/.secrets/sql_powerdns.password)

cat >/tmp/byodadns.sql <<EOF
CREATE DATABASE byodadns;
CREATE USER powerdns PASSWORD '${SQL_DNS_PASSWORD}';
GRANT ALL ON DATABASE byodadns TO powerdns;
EOF

psql -h localhost -U postgres -d postgres -f /tmp/byodadns.sql
rm /tmp/byodadns.sql

psql -h localhost -U powerdns -d byodadns -f docs/powerdns-pgsql.schema
```

## Set up a DNS server
The ACLs for the server should allow TCP/UDP port 53 from anywhere and port 9191 from trusted IPs. All other ports should be blocked for external traffic.


- Set up the name server
PowerDNS

```
sudo apt-get install pdns-server
sudo apt-get install pdns-backend-pgsql
sudo systemctl disable --now systemd-resolved
sudo systemctl stop pdns

if [ ! -f ~/.secrets/powerdns-api.key ]; then
  passgen -n 1 >~/.secrets/powerdns-api.key
fi
API_KEY=$(cat ~/.secrets/powerdns-api.key)

sudo -i

cat >/etc/powerdns/pdns.conf <<EOF
launch+=gpgsql
gpgsql-host=${SERVER_IP}
gpgsql-port=5432
gpgsql-dbname=byodadns
gpgsql-user=powerdns
gpgsql-password=${SQL_DNS_PASSWORD}
gpgsql-dnssec=yes
EOF


cat >/etc/powerdns/http.conf <<EOF
webserver=yes
webserver-address=0.0.0.0
webserver-allow-from=127.0.0.1,192.168.0.0/24
api=yes
api-key=${API_KEY}
EOF

```

This table modification allows us to remove FQDNS from the database 1 week after they've last registered

```
ALTER TABLE RECORDS ADD db_expire integer;
```

Using  http://${DIRSERVER}:9191/login, create DNS zone for byoda.net with NS records for subdomains {accounts,services,members}.byoda.net

```
docker run -d --restart unless-stopped \
    -e SECRET_KEY=${API_KEY} \
    -v pda-data:/data \
    -p 9191:80 \
    --name pdns-admin \
    ngoduykhanh/powerdns-admin:latest
```

## Create your CA

Each network has the following secrets:
- Network Root CA: self-signed, store off-line
- Network Services CA: signed by Network Root CA, signs CSRs for the ServiceCA of each service in the network
- Network Accounts CA: signed by the Network Root CA, signs CSRs for pods/clients
- Network Data: Signed by Network Root CA, used to sign documents such as service schemas/data contracts so pods/clients can validate that the service is supported by the network

On a private server, preferably air-gapped:
```
cd ${BYODA_HOME}
git clone https://github.com/StevenHessing/byoda-python
cd byoda-python
pipenv shell

BYODA_DOMAIN=somecooldomain.net

# This password is used for intermediate network CAs, not the network root CA
PASSWORD=$(passgen -n 1 -l 48)

export PYTHONPATH=${PYTHONPATH}:$(pwd)
export ROOT_DIR=/opt/byoda/dirserver
tools/create_network.py --debug --network ${BYODA_DOMAIN} --root-dir=${ROOT_DIR} --password ${PASSWORD} 2>&1 | tee /tmp/network.log
# Save the password for the root CA from the log message containing:
#   'Saving root CA using password'
# to your password manager like 1password, keepass2, lastpass etc.
# and them 'rm /tmp/network.log'

# copy all files except the private key for the root ca from the tempoarily
# not air-gapped server to the directory server
ssh ${DIRSERVER} "sudo mkdir ${BYODA_HOME}/{private,network-${BYODA_DOMAIN}}
ssh ${DIRSERVER} "sudo chown -R $USER ${BYODA_HOME}"
scp ~/.byoda/private/network-${BYODA_DOMAIN}-{accounts-ca,services-ca,data}.key \
     ${DIRSERVER}:${BYODA_HOME}/private/
scp ~/.byoda/network-${BYODA_DOMAIN} ${DIRSERVER}:${BYODA_HOME}/network-${BYODA_DOMAIN}

- Set up the directory server

This is the public server that exposes the APIs

Byoda code requires python 3.9 or later, ie. for Ubuntu:
```
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get -y install python3.9 pipenv
```
or run a distribution (like Ubuntu 21.04 or later) that includes python3.9


There is currently an issue with 'pipenv' to install the modules so we install
python modules globally:

```
sudo pip install -r requirements.txt
```

Clone the repo:
```
BYODA_HOME=/opt/byoda
sudo mkdir ${BYODA_HOME}
sudo chown -R $USER:$USER ${BYODA_HOME}
git clone https://github.com/StevenHessing/byoda-python
cd byoda-python
sudo cp docs/files/gunicorn-systemd /etc/systemd/system/dirserver.service
sudo systemctl daemon-reload
sudo systemctl enable dirserver
cp config-sample.yml config.yml
```

Edit the config.yml, including the connection string for your Postgres server


We install nginx as reverse proxy in for the directory server:
```
sudo apt install nginx
sudo rm -f /etc/nginx/conf.d/default.conf
sudo cp ${BYODA_HOME}/byoda-python/docs/files/dirserver-nginx-virtualserver.conf /etc/nginx/conf.d/default.conf

sed -i "s|{{ BYODA_HOME }}|${BYODA_HOME}|g" /etc/nginx/conf.d/default.conf
sed -i "s|{{ BYODA_DIR }}|${BYODA_DIR}|g" /etc/nginx/conf.d/default.conf
```

You can't start NGINX just yet as the directory server must have a trusted TLS cert/key. Set up a [Let's Encrypt](https://www.letsencrypt.org) install on the directory server. Please follow the instructions from Let's Encrypt on how to do this. I recommend adding a virtual server to nginx for HTTP on port 80 for web-based verification of ownership of your domain and installing a cronjob to renew the cert/key periodically.

Now we just have to start nginx and the directory server

```
sudo systemctl start dirserver nginx
```

It is necessary to run a reverse proxy to support browser clients. Browsers do not use the root CA cert of the Byoda network so will refuse to connect to the pod directly. The convention is that clients can connect to:
https://proxy.<network-domain>/<service_id>/<member_id> to connect to the pod.

You will need to request an SSL certificate for 'proxy.<network-domain>'. Nginx can be used as a reverse proxy with the following virtual server configuration:
```
server {
    listen       443 ssl http2 backlog=16384 fastopen=4096 deferred reuseport default_server;

    server_name  proxy.<network>;

    ssl_certificate /etc/letsencrypt/live/proxy.<network>/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/proxy.<network>/privkey.pem;

    ssl_verify_client off;

    proxy_ssl_verify_depth 4;
    proxy_ssl_server_name on;
    proxy_ssl_verify on;
    proxy_ssl_protocols TLSv1.3;
    proxy_ssl_trusted_certificate /opt/byoda/dirserver/network-<network>/network-<network>-root-ca-cert.pem;

    location / {
        root   /var/www/wwwroot/proxy.<network>/;
        add_header X-Frame-Options DENY;
        add_header X-Content-Type-Options nosniff;
        add_header X-XSS-Protection "1; mode=block";
    }

    location ~ ^\/(?<service>\d+)\/(?<memberid>[\da-fA-F\-]+)\/(?<api>.*)$ {
        proxy_pass https://$memberid.members-$service.<network>/$api;
    }
}
