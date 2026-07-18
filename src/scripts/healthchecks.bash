#!/usr/bin/env bash
# Shared Healthchecks helpers, sourced as ./scripts/healthchecks.bash by src/run-manage.bash
# and by legacy/update.bash (the legacy container bind-mounts ./src/scripts).
# Pings are best-effort and never fail the wrapped command. Checks are provisioned by
# config/healthchecks/provision.py; we only ping existing ones (no `create=1`).

# Load the monitoring secret (HEALTHCHECKS_*) into the environment.
hc_load_monitoring_conf() {
  local conf=${MONITORING_CONF_FILE:-/run/secrets/monitoring_conf}
  if [ -f "$conf" ]; then
    set -a
    . "$conf"
    set +a
  fi
}

# Best-effort ping; args are extra curl args followed by the URL.
hc_ping() { curl -fsS -m 10 --retry 3 -o /dev/null "$@" || true; }

# Echo the ping URL for a monitor, or nothing if monitoring is not configured.
hc_ping_url() {
  local monitor_name=$1
  if [ -n "$monitor_name" ] && [ -n "$HEALTHCHECKS_PING_URL" ] && [ -n "$HEALTHCHECKS_PING_KEY" ]; then
    printf '%s/%s/%s' "$HEALTHCHECKS_PING_URL" "$HEALTHCHECKS_PING_KEY" "$monitor_name"
  fi
}

# Run a command under a monitor, teeing output to a log. Pings /start then /<rc>, with the
# log tail as the failure ping body (capped server-side by PING_BODY_LIMIT).
# Usage: hc_run <monitor_name> <logfile> <command> [args...]
hc_run() {
  local monitor_name=$1 logfile=$2
  shift 2
  local ping_url
  ping_url=$(hc_ping_url "$monitor_name")
  [ -n "$ping_url" ] && hc_ping "$ping_url/start"
  "$@" 2>&1 | tee -a "$logfile"
  local rc=${PIPESTATUS[0]}
  if [ "$rc" -ne 0 ]; then
    echo "FAILED rc=$rc: $*" | tee -a "$logfile"
  fi
  if [ -n "$ping_url" ]; then
    if [ "$rc" -eq 0 ]; then
      hc_ping "$ping_url/$rc"
    else
      tail -c 10000 "$logfile" | hc_ping --data-binary @- "$ping_url/$rc"
    fi
  fi
  return "$rc"
}
