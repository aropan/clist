#!/usr/bin/env bash

name=$1

exec 200>/tmp/$name.lock
flock -n 200 || { date; echo "Script '$name' is already running"; exit 0; }

SENTRY_CONF_FILE=/run/secrets/sentry_conf
if [ -f $SENTRY_CONF_FILE ]; then
  export $(cat $SENTRY_CONF_FILE | xargs)
fi

cd "$(dirname "$0")"
logdir=./logs/manage
logfile=$logdir/$name.log
mkdir -p $logdir
rm -f $logfile
echo -e "BEGIN $(date)\n\n" >>$logfile

cmd="./manage.py $@"
if [ -n "$MONITOR_NAME" ]; then
  monitor_id=${!MONITOR_NAME}
fi
if [ -n "$monitor_id" ]; then
  sentry-cli monitors run $monitor_id -- $cmd 2>&1
else
  $cmd 2>&1
fi | tee -a $logfile

echo -e "\n\nEND $(date)" >>$logfile
