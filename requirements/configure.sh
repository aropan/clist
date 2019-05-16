#!/usr/bin/env bash

set -e -x

wget -O /etc/bash_completion.d/django_bash_completion.sh https://raw.github.com/django/django/master/extras/django_bash_completion

mkdir -p /var/log/nginx/clist/
mkdir -p /var/log/nginx/clist/legacy/


pgdata=($(cat $(dirname $BASH_SOURCE[0])/../.pgpass | tr ":" " "))

PGUSER=${pgdata[3]}
PGPASSWORD=${pgdata[4]}
PGDATABASE=${pgdata[2]}

sudo -u postgres createuser $PGUSER || :
sudo -u postgres createdb $PGDATABASE || :

sudo -u postgres psql -c "alter user $PGUSER with encrypted password '$PGPASSWORD';"
sudo -u postgres psql -c "grant all privileges on database $PGDATABASE to $PGUSER;"
