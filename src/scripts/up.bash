#!/usr/bin/env bash

set -e -x

cd "$(dirname "$0")"

docker compose up --detach


function allow_to_proxy() {
  name=$1
  ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' clist-$name-1)
  bridge="br-clist"
  proxy_port=3128
  comment="from $name to proxy"
  sudo ufw status numbered | grep "# $comment" | grep -o -E "[0-9]+" | head -n 1 | xargs --no-run-if-empty -I {} sh -c 'yes | sudo ufw delete {}'
  sudo ufw allow in on $bridge from $ip to any port $proxy_port comment "$comment"
}

allow_to_proxy "dev"
allow_to_proxy "legacy"


sudo ufw-docker allow clist-nginx-1 443/tcp
sudo ufw-docker allow clist-nginx-1 80/tcp
docker compose exec nginx nginx -s reload
