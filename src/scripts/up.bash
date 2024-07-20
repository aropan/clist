#!/usr/bin/env bash

set -e -x

cd "$(dirname "$0")"

docker compose up --detach

sudo ufw-docker allow clist-nginx-1 443/tcp
sudo ufw-docker allow clist-nginx-1 80/tcp
