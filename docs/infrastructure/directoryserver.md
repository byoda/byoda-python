Byoda code requires python 3.9 or later, ie. for Ubuntu:
```
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get -y install python3.9 pipenv
```

- Set up a domain
You need a domain, such as byoda.net

- Set up a database server
Postgres

mkdir -p ~/.secrets
chmod 700 ~/.secrets

passgen -n 1 >~/.secrets/postgres.password

export POSTGRES_PASSWORD=$(cat ~/.secrets/postgres.password)

# https://github.com/docker-library/postgres
docker run -d --restart unless-stopped \
    --publish=5432:5432 \
    -v /var/lib/postgresql/data:/var/lib/postgresql/data \
    -e POSTGRES_PASSWORD=${POSTGRES_PASSWORD} \
    --name postgres \
     postgres:latest

apt install postgresql-client-common
sudo apt install postgresql-client

passgen -n 1 >~/.secrets/sql_powerdns.password
export SQL_DNS_PASSWORD=$(cat ~/.secrets/sql_powerdns.password)

echo "*:*:postgres:postgres:${POSTGRES_PASSWORD}" >~/.pgpass
echo "*:*:byodadns:powerdns:${SQL_DNS_PASSWORD}" >>~/.pgpass
chmod 600 ~/.pgpass

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
gpgsql-host=192.168.1.11
gpgsql-port=5432
gpgsql-dbname=byodadns
gpgsql-user=powerdns
gpgsql-password=D1YHp4S2mI3e
gpgsql-dnssec=yes
EOF


cat >/etc/powerdns/http.conf <<EOF
webserver=yes
webserver-address=0.0.0.0
webserver-allow-from=127.0.0.1,192.168.1.0/24
api=yes
api-key=hLYM6Vgv4a2J
EOF

create DNS zones for accounts.byoda.net, services.byoda.net and members.byoda.net

# This table allows us to remove FQDNS from the database 1 week after they've last registered

ALTER TABLE RECORDS ADD db_expire integer;

Create DNS zone for byoda.net with NS records for {accounts,services,members}.byoda.net

docker run -d --restart unless-stopped\
    -v pda-data:/data \
    -p 9191:80 \
    --name pdns-admin \
    ngoduykhanh/powerdns-admin:latest

```

- Create your CA
- Set up the directory server
- Set up the DNS records