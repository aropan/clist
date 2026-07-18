#!/usr/bin/env bash

# No `set -x`: the ping key is part of the ping URL, so xtrace would leak it to the log.
set -e

exec 200>/tmp/update.lock
flock -n 200 || { date; echo "Script is already running"; exit 0; }

cd "$(dirname "${BASH_SOURCE[0]}")"

# Shared with run-manage.bash; ./scripts is ./src/scripts bind-mounted in (docker-compose.yml).
. ./scripts/healthchecks.bash
hc_load_monitoring_conf

logdir=logs
logfile=$logdir/update.log
mkdir -p $logdir
rm -f $logfile
echo -e "BEGIN $(date)\n\n" >>$logfile

# Refresh the Google OAuth token used by update.php's calendar sync (best-effort).
python3 api/google_calendar/common.py || true

rc=0
hc_run list-update "$logfile" php -f update.php || rc=$?

echo -e "\n\nEND $(date)" >>$logfile
exit $rc
