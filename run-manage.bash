#!/usr/bin/env bash

name=${@:$#}

exec 200>/tmp/$name.lock
flock -n 200 || { date; echo "Script '$name' is already running"; exit 0; }

cd "$(dirname "$0")"
logdir=./logs/manage
mkdir -p $logdir
./manage.py "$@" 2>&1 | tee $logdir/$name.log
