#!/usr/bin/env bash

set -x

root=$(cd $(dirname ${BASH_SOURCE[0]}); cd ..; pwd)

certbot certonly --webroot -w $root -d clist.by
