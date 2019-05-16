#!/usr/bin/env bash

cd "$(dirname "${BASH_SOURCE[0]}")"

mkdir -p logs/update
mkdir -p logs/working
php -f update.php 2>&1 | tee logs/update/index.html

mkdir -p logs/calendar
$WORKON_HOME/clist/bin/python -W ignore::DeprecationWarning calendar/update.py 2>&1 | tee logs/calendar/index.txt
