#!/usr/bin/env bash

name=$1

exec 200>/tmp/$name.lock
flock -n 200 || { date; echo "Script '$name' is already running"; exit 0; }

MONITORING_CONF_FILE=/run/secrets/monitoring_conf
if [ -f $MONITORING_CONF_FILE ]; then
  export $(cat $MONITORING_CONF_FILE | xargs)
fi

cd "$(dirname "$0")"
logdir=./logs/manage
logfile=$logdir/$name.log
mkdir -p $logdir
rm -f $logfile
echo -e "BEGIN $(date)\n\n" >>$logfile

cmd="./manage.py $@"
ping_url=
if [ -n "$MONITOR_NAME" ] && [ -n "$HEALTHCHECKS_PING_URL" ] && [ -n "$HEALTHCHECKS_PING_KEY" ]; then
  ping_url=$HEALTHCHECKS_PING_URL/$HEALTHCHECKS_PING_KEY/$MONITOR_NAME
  curl -fsS -m 10 --retry 3 -o /dev/null "$ping_url/start?create=1" || true
fi
$cmd 2>&1 | tee -a $logfile
rc=${PIPESTATUS[0]}
if [ -n "$ping_url" ]; then
  curl -fsS -m 10 --retry 3 -o /dev/null "$ping_url/$rc" || true
fi

echo -e "\n\nEND $(date)" >>$logfile
