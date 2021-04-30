#!/usr/bin/env bash

set -e -x

add-apt-repository -y ppa:nginx/stable

apt -y install vim bash-completion wget
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
echo "deb http://apt.postgresql.org/pub/repos/apt/ `lsb_release -cs`-pgdg main" |sudo tee  /etc/apt/sources.list.d/pgdg.list

apt update
apt upgrade -y
apt install -y bash-completion
apt install -y protobuf-compiler
apt install -y php-curl php-imap php-pspell php-tidy php-xmlrpc php-fxsl php-sqlite3 php-pgsql php-cgi php-mysql php-curl php-gd php-json php-memcache php-fpm php-mbstring php-intl php-yaml

apt install -y python3-pip python3-dev python3-venv

apt install -y nginx
update-rc.d nginx enable

apt install -y uwsgi uwsgi-plugin-python3
update-rc.d uwsgi enable

apt install -y certbot python3-certbot-nginx

apt install -y postgresql postgresql-contrib

apt install -y memcached
update-rc.d memcached enable

yes | pip3 install virtualenv
yes | pip3 install wheel
