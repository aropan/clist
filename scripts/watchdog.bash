##!/usr/bin/env bash

set -e -x

command=$1
pattern=$2

nohup $command &

nohup watchmedo shell-command . \
  --patterns=$pattern \
  --recursive \
  --command='echo ${watch_src_path} has changed; pkill -f '\''^'"$command"'$'\''; '"$command"' &' \
  --drop \
  &
