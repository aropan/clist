#!/usr/bin/env bash

set -e -x

wget -O /etc/bash_completion.d/django_bash_completion.sh https://raw.github.com/django/django/master/extras/django_bash_completion

while IFS= read -r line; do
    export $line
done <<< $(cat "$(dirname $BASH_SOURCE[0])/../pyclist/conf.py" | grep " = " | sed "s/ = '\?/=/;s/'$//")

sudo -u postgres createuser $DB_USER || :
sudo -u postgres createdb $DB_NAME || :

sudo -u postgres psql -c "alter user $DB_USER with encrypted password '$DB_PASSWORD';"
sudo -u postgres psql -c "grant all privileges on database $DB_NAME to $DB_USER;"
