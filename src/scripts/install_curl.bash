#!/usr/bin/env bash

set -e -x

pushd $(dirname "$0")

curl_version="8.17.0"
os_arch=$(uname -m)
os_name=$(uname -s)
if [ "$os_name" = "Linux" ]; then
    os_name="linux"
    os_arch="${os_arch}-glibc"
elif [ "$os_name" = "Darwin" ]; then
    os_name="macos"
fi

wget https://github.com/stunnel/static-curl/releases/download/${curl_version}/curl-${os_name}-${os_arch}-${curl_version}.tar.xz -O /tmp/curl.tar.xz
tar -xvf /tmp/curl.tar.xz -C /tmp
sha256=$(sha256sum /tmp/curl | cut -d ' ' -f 1)
echo $sha256
grep -q "$sha256" install_curl.sums
mv /tmp/curl /usr/local/bin/curl
rm /tmp/curl.tar.xz

popd