#!/bin/bash

# install pgloader if it is not available
if [ -f /usr/bin/pgloader ]; then
  echo "pgloader already installed"
else
  sudo apt-get update
  sudo apt-get install -y pgloader
fi

if [ -f /usr/bin/psql ]; then
  echo "psql already installed"
else
  sudo apt-get update
  sudo apt-get install -y postgresql-client
fi


source /home/ubuntu/byoda-generic-settings.sh


if [[ ${HOSTNAME:0:4} == "byo-" ]]; then
    export POSTFIX=$HOSTNAME
fi
if [[ ${HOSTNAME} == 'dathes' || ${HOSTNAME} == 'notest' || ${HOSTNAME} == 'demotest' || ${HOSTNAME} == 'dmz' ]]; then
    export POSTFIX=$HOSTNAME
fi

export DIR=$(ls -d /byoda/${POSTFIX}/private/network-byoda.net/account-pod/data/network-byoda.net-member*)

MEMBER_ID="$(echo ${DIR: -36})"
SERVICE_ID=16384
BACKUP_DB=/home/ubuntu/backup.db

postgress_pass=$(grep -c POSTGRESS_PASSWORD /home/ubuntu/byoda-generic-settings.sh)
if [ "${postgress_pass}" == "0" ]; then
  echo "export POSTGRESS_PASSWORD=byoda" >> /home/ubuntu/byoda-generic-settings.sh
fi

pg_pass=$(grep -c PG_PASSWORD /home/ubuntu/byoda-generic-settings.sh)
if [ "${postgress_pass}" == "0" ]; then
  echo "export PGPASSWORD=byoda" >> /home/ubuntu/byoda-generic-settings.sh
fi

sudo mkdir -p /var/lib/postgresql/${POSTFIX}/data

# Delete data we don't care for from the Sqlite database
sqlite3 ${DIR}/data*.db 'DELETE FROM _datalogs; DELETE FROM _incoming_assets; DELETE FROM _feed_assets'

cp $DIR/data*.db $BACKUP_DB

# find the progres pod.
export PIP=172.18.0.3
nc -w 2 -v $PIP 5432
if [ $? -ne 0 ]; then
  export PIP=172.18.0.4
  nc -w 2 -v $PIP 5432
  if [ $? -ne 0 ]; then
    export PIP=172.18.0.2
    nc -w 2 -v $PIP 5432
    if [ $? -ne 0 ]; then
      echo "Postgres pod not found"
      exit 1
    fi
  fi
fi

sudo pkill -f pod_worker

export PGPASSWORD=byoda


psql -U postgres -h ${PIP} -c "CREATE DATABASE byoda;"

for TABLE in _asset_links _asset_reactions_received _channels _datalogs _member _messages _network_invites _network_links _network_links_inbound _public_assets _restricted_content_keys _feed_assets _incoming_assets _asset_reactions _private_messages _burst_point_attestations_received _financial_transaction_receipts; do


  # Delete the table that byoda pod may have already created
    sed "s|TABLE_VAR|${TABLE}|g" migration.loader | sed "s|HOST_IP|${PIP}|" >/tmp/migration.loader-${TABLE}

  echo "Migrating table: ${TABLE}"
  pgloader /tmp/migration.loader-${TABLE}

  echo "Renaming table ${TABLE} to ${TABLE}_${SERVICE_ID}"
  psql -U postgres -h ${PIP} byoda -c "ALTER TABLE ${TABLE} RENAME TO ${TABLE}_${SERVICE_ID}"
  psql -U postgres -h ${PIP} byoda -c "ALTER TABLE ${TABLE}_${SERVICE_ID} ADD COLUMN rowid SERIAL;"
done
