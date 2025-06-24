#!/usr/bin/env bash

set -e

function allow_to_proxy() {
  name=$1
  ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' clist-$name-1)
  bridge="br-clist"
  proxy_port=3128
  comment="from $name to proxy"

  existing_rule=$(sudo ufw status numbered | grep "$comment" | grep "$ip")
  if [ -n "$existing_rule" ]; then
    echo "Rule already exists: $existing_rule"
    return
  fi

  rule_number=$(sudo ufw status numbered | grep "# $comment" | grep -o -E "[0-9]+" | head -n 1)
  if [ -n "$rule_number" ]; then
    yes | sudo ufw delete $rule_number
  fi
  (set -x; sudo ufw allow in on $bridge from $ip to any port $proxy_port comment "$comment")
}

allow_to_proxy "prod"
allow_to_proxy "dev"
allow_to_proxy "legacy"
