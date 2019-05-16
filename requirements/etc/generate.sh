#!/usr/bin/env bash

set -x

work_dir=$(cd $(dirname ${BASH_SOURCE[0]}); pwd)

export PROJECT_DIR=$(cd $work_dir; cd ..; cd ..; pwd)
export DOLLAR='$'

for template in $(find $work_dir -name '*.template'); do
  target=${template%%.template}
  cat $template | envsubst > $target
done
