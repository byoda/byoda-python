# Setting up a BYODA network

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
passgen -n 1 >~/.secrets/postgres.password

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
     postgres:latest

sudo apt-get -y install postgresql-client-common
sudo apt-get -y install postgresql-client

echo "*:*:postgres:postgres:${POSTGRES_PASSWORD}" >~/.pgpass
echo "*:*:byodadns:powerdns:${SQL_DNS_PASSWORD}" >>~/.pgpass
chmod 600 ~/.pgpass

export SERVERIP=$(curl http://ifconfig.co)

passgen -n 1 >~/.secrets/sql_powerdns.password
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

## Set up a DNS server (or more)
The ACLs for the server should allow TCP/UDP port 53 from anywhere and port 9191 from trusted IPs. All other ports should be blocked for external traffic.


- Set up the name server
PowerDNS

```
sudo apt-get install pdns-server
sudo apt-get install pdns-backend-pgsql
sudo systemctl disable --now systemd-resolved
sudo systemctl stop pdns

passgen -n 1 >~/.secrets/powerdns-api.key
APIKEY=$(cat ~/.secrets/powerdns-api.key)

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

Using  http://${SERVERIP}:9191/login, create DNS zone for byoda.net with NS records for subdomains {accounts,services,members}.byoda.net

```
docker run -d --restart unless-stopped\
    -v pda-data:/data \
    -p 9191:80 \
    --name pdns-admin \
    ngoduykhanh/powerdns-admin:latest
```

- Create your CA
On a private server, preferably air-gapped,
```
git clone https://github.com/StevenHessing/byoda-python
cd byoda-python
pipenv shell

BYODA_DOMAIN=somecooldomain.net

# This password is used for intermediate network CAs, not the network root CA
PASSWORD=$(passgen -n 1 -l 48)

tools/create_network.py --network ${BYODA_DOMAIN} --debug --password ${PASSWORD} 2>&1 | /tmp/network.log
# Save the password for the root CA from the log message containing:
#   'Saving root CA using password'
# to your password manager like 1password, keepass2, lastpass etc.
# and them 'rm /tmp/network.log'

# copy all files except the private key for the root ca from the tempoarily
# not air-gapped server to the directory server
ssh ${DIRSERVER} "sudo mkdir /var/lib/byoda/{private,network-${BYODA_DOMAIN}}
ssh ${DIRSERVER} "sudo chown -R $USER /var/lib/byoda"
scp ~/.byoda/private/network-${BYODA_DOMAIN}-{accounts-ca,services-ca,data}.key \
     ${DIRSERVER}:/var/lib/byoda/private/
scp ~/.byoda/network-${BYODA_DOMAIN} ${DIRSERVER}:/var/lib/byoda/network-${BYODA_DOMAIN}

- Set up the directory server

This is the public server that exposes the APIs

Byoda code requires python 3.9 or later, ie. for Ubuntu:
```
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get -y install python3.9 pipenv
```
or run a distribution (like Ubuntu 21.04 or later) that includes python3.9


- Set up the DNS records