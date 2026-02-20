#!/usr/bin/env bash

set -x -e

CONTAINER_ID="$(docker compose ps -q nginx || true)"
if [[ -z "${CONTAINER_ID}" ]]; then
    echo "nginx container is not running; start it before updating ufw rules" >&2
    exit 1
fi

CONTAINER_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "${CONTAINER_ID}")
if [[ -z "${CONTAINER_IP}" ]]; then
    echo "Could not find IP for container ${CONTAINER_ID}" >&2
    exit 1
fi


# Cloudflare IPs
CLOUDFLARE_IPS_V4_URL="https://www.cloudflare.com/ips-v4"

# Fetch IPs
REGEX_V4="^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$"
declare -A CF_IPS
for url in "${CLOUDFLARE_IPS_V4_URL}"; do
    mapfile -t IPS < <(curl -sL "${url}")
    for ip in "${IPS[@]}"; do
        if [[ "${ip}" =~ ${REGEX_V4} ]]; then
            CF_IPS["${ip}"]=true
        fi
    done
done

for port in 443 80; do
    # Remove catch-all rule
    sudo ufw-docker delete allow "${CONTAINER_ID}" "${port}/tcp" || true

    # Add Cloudflare IPs
    for ip in "${!CF_IPS[@]}"; do
        sudo ufw route allow proto tcp from "${ip}" to "${CONTAINER_IP}" port "${port}" comment 'allow from Cloudflare to CLIST'
    done

    # Remove stale rules
    # Parsing 'ufw status' output:
    # Example: 10.42.0.101 443/tcp ALLOW FWD 104.24.0.0/14 # allow from Cloudflare to CLIST
    # Columns are separated by multiple spaces.
    sudo ufw status | grep "${CONTAINER_IP}" | grep "${port}/tcp" | while read -r line; do
        src_ip=$(echo "$line" | awk '{print $5}')
        if [[ -z "${CF_IPS["${src_ip}"]}" ]]; then
            sudo ufw route delete allow proto tcp from "${src_ip}" to "${CONTAINER_IP}" port "${port}"
        fi
    done
done

docker compose exec nginx nginx -s reload
