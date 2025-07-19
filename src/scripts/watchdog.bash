#!/usr/bin/env bash

set -e -x

command=$1
pattern=$2

nohup $command &

watch_dirs=($(ls -d */ | grep -Ev '^(volumes|staticfiles|mediafiles|logs)/$'))

nohup watchmedo shell-command "${watch_dirs[@]}" \
  --patterns="$pattern" \
  --recursive \
  --ignore-directories \
  --command='echo ${watch_src_path} has changed; pkill -f '\''^'"$command"'$'\''; '"$command"' &' \
  --drop \
  &
