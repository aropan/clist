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

# Best-effort Healthchecks ping (never fails the script); extra curl args + URL.
hc_ping() { curl -fsS -m 10 --retry 3 -o /dev/null "$@" || true; }

cmd="./manage.py $@"
ping_url=
if [ -n "$MONITOR_NAME" ] && [ -n "$HEALTHCHECKS_PING_URL" ] && [ -n "$HEALTHCHECKS_PING_KEY" ]; then
  ping_url=$HEALTHCHECKS_PING_URL/$HEALTHCHECKS_PING_KEY/$MONITOR_NAME
  hc_ping "$ping_url/start"
fi
$cmd 2>&1 | tee -a $logfile
rc=${PIPESTATUS[0]}
if [ -n "$ping_url" ]; then
  if [ "$rc" -eq 0 ]; then
    hc_ping "$ping_url/$rc"
  else
    # On failure attach the log tail as the body so the traceback shows on the
    # check page (capped server-side by PING_BODY_LIMIT, default 10000).
    tail -c 10000 "$logfile" | hc_ping --data-binary @- "$ping_url/$rc"
  fi
fi

echo -e "\n\nEND $(date)" >>$logfile
