#!/usr/bin/env bash

set -x -e

cd "$(dirname "${BASH_SOURCE[0]}")"

$VIRTUAL_ENV/bin/python -W ignore::DeprecationWarning api/google-calendar/common.py 2>&1

mkdir -p logs/update
mkdir -p logs/working
php -f update.php 2>&1 | tee logs/update/index.html

mkdir -p logs/calendar
$VIRTUAL_ENV/bin/python -W ignore::DeprecationWarning calendar/update.py 2>&1 | tee logs/calendar/index.txt
