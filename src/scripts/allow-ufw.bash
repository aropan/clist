#!/usr/bin/env bash

set -x

container="$(docker compose ps -q nginx || true)"

if [[ -z "${container}" ]]; then
    echo "nginx container is not running; start it before updating ufw rules" >&2
    exit 1
fi

sudo ufw-docker allow "${container}" 443/tcp
sudo ufw-docker allow "${container}" 80/tcp
docker compose exec nginx nginx -s reload
