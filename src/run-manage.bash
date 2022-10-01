#!/usr/bin/env bash

name=${@:$#}

exec 200>/tmp/$name.lock
flock -n 200 || { date; echo "Script '$name' is already running"; exit 0; }

cd "$(dirname "$0")"
logdir=./logs/manage
logfile=$logdir/$name.log
mkdir -p $logdir
rm -f $logfile
echo -e "BEGIN $(date)\n\n" >>$logfile
./manage.py "$@" 2>&1 | tee -a $logfile
echo -e "\n\nEND $(date)" >>$logfile
