#!/usr/bin/env bash

TOKEN=$(cat /run/secrets/loggly_token)
sed "s/LOGGLY_TOKEN_PLACEHOLDER/$TOKEN/g" -i /etc/rsyslog.d/60-loggly.conf

set -x -e

mkdir -p /logs/loggly/
chmod -R 777 /logs/loggly/

/usr/sbin/rsyslogd -n
