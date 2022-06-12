#!/usr/bin/env bash

set -e -x

sudo -u postgres createuser $DB_USER || :
sudo -u postgres createdb -E utf8 $DB_NAME || :

sudo -u postgres psql -c "alter user $DB_USER with encrypted password '$DB_PASSWORD';"
sudo -u postgres psql -c "grant all privileges on database $DB_NAME to $DB_USER;"
