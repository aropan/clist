#!/usr/bin/env bash

set -x -e -u

work_dir=$(cd $(dirname ${BASH_SOURCE[0]}); pwd)

export PROJECT_DIR=$(cd $work_dir; cd ..; cd ..; pwd)
export DOLLAR='$'
export PORT=${PORT:-80}
export CHANNELS_PORT=${CHANNELS_PORT:-9042}

service=""
if [[ $# -gt 0 ]]; then
  service=$1
  shift
fi

for template in $(find $work_dir -name '*.template'); do
  target=${template%%.template}
  if [[ -n "$service" ]] && ! grep -q $service <<<$target; then
    continue
  fi
  cat $template | envsubst > $target
done
