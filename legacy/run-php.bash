#!/usr/bin/env bash

echo "" | php -R "include('$1');" -B 'parse_str($argv[1], $_GET);' "$2"
