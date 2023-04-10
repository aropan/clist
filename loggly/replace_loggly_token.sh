#!/usr/bin/env bash
TOKEN=$(cat /run/secrets/loggly_token)
sed "s/LOGGLY_TOKEN_PLACEHOLDER/$TOKEN/g" -i /etc/rsyslog.d/60-loggly.conf
