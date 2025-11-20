#!/usr/bin/env bash

set -e -x

cd "$(dirname "$0")"

docker compose up --detach

./allow-ufw.bash
