Byoda code requires python 3.9 or later, ie. for Ubuntu:
```
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get -y install python3.9 pipenv
```
or run a distribution (like Ubuntu 21.04 or later) that includes python3.9

- Set up a domain
You need a domain, we'll use 'byoda.net' as example here. You'll have to register the
domain with a domain registrar (like [hover.com](https://www.hover.com/)) and create NS records that point to the public IP address of your server.

- Set up a database server
The ACLs for the server should allow TCP/UDP port 53 from anywhere and port 9191 from trusted IPs. All other ports should be blocked for external traffic.

Postgres

mkdir -p ~/.secrets
chmod 700 ~/.secrets

passgen -n 1 >~/.secrets/postgres.password

export POSTGRES_PASSWORD=$(cat ~/.secrets/postgres.password)

sudo mkdir -p /var/lib/postgresql/data
sudo chown -R 999:999 /var/lib/postgresql/

# https://github.com/docker-library/postgres
sudo docker run -d --restart unless-stopped \
    --publish=5432:5432 \
    -v /var/lib/postgresql/data:/var/lib/postgresql/data \
    -e POSTGRES_PASSWORD=${POSTGRES_PASSWORD} \
    --name postgres \
     postgres:latest

sudo apt install postgresql-client-common
sudo apt install postgresql-client

passgen -n 1 >~/.secrets/sql_powerdns.password
export SQL_DNS_PASSWORD=$(cat ~/.secrets/sql_powerdns.password)

echo "*:*:postgres:postgres:${POSTGRES_PASSWORD}" >~/.pgpass
echo "*:*:byodadns:powerdns:${SQL_DNS_PASSWORD}" >>~/.pgpass
chmod 600 ~/.pgpass

export SERVERIP=$(curl ifconfig.co)

cat >/tmp/byodadns.sql <<EOF
CREATE DATABASE byodadns;
CREATE USER powerdns PASSWORD '${SQL_DNS_PASSWORD}';
GRANT ALL ON DATABASE byodadns TO powerdns;
EOF

psql -h localhost -U postgres -d postgres -f /tmp/byodadns.sql
rm /tmp/byodadns.sql

psql -h localhost -U powerdns -d byodadns -f docs/powerdns-pgsql.schema
"

- Set up the name server
PowerDNS

```
sudo apt-get install pdns-server
sudo apt-get install pdns-backend-pgsql
sudo systemctl disable --now systemd-resolved
sudo systemctl stop pdns
passgen -n 1 >~/.secrets/powerdns-api.key

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
webserver-allow-from=127.0.0.1,192.168.1.0/24
api=yes
api-key=<api-key>
EOF

create DNS zones for accounts.byoda.net, services.byoda.net and members.byoda.net

# This table allows us to remove FQDNS from the database 1 week after they've last registered

ALTER TABLE RECORDS ADD db_expire integer;

Using  http://${SERVERIP}:9191/login

Create DNS zone for byoda.net with NS records for {accounts,services,members}.byoda.net

docker run -d --restart unless-stopped\
    -v pda-data:/data \
    -p 9191:80 \
    --name pdns-admin \
    ngoduykhanh/powerdns-admin:latest

```

- Create your CA
On a private server, preferably air-gapped,
git clone https://github.com/StevenHessing/byoda-python
cd byoda-python
pipenv shell
# This password is used for intermediate network CAs, not the network root CA
PASSWORD=$(passgen -n 1 -l 48)
tools/create_network.py --network byoda.net --debug --password ${PASSWORD}
# Save the password for the root CA from the log messages to your password manager like 1password, keepass2, lastpass etc.

- Set up the directory server
- Set up the DNS records