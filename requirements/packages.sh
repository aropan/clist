#!/usr/bin/env bash

set -e -x

apt update

# apt install -y protobuf-compiler
apt install -y certbot python3-certbot-nginx

apt install -y memcached
update-rc.d memcached enable

apt install -y tesseract-ocr tesseract-ocr-eng
tessdata=$(sudo find / -name "tessdata" | head -n 1)
if [ -n "$tessdata" ]; then
  pushd "$tessdata"
  wget --quiet -O eng.traineddata https://github.com/tesseract-ocr/tessdata/raw/master/eng.traineddata
  popd
fi
