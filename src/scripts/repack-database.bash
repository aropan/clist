#!/usr/bin/env bash

date
echo

name=repack_database
exec 200>/tmp/$name.lock
flock -n 200 || { echo "Script '$name' is already running"; exit 0; }


function human_readable_size {
  local size=$1
  if [ $size -lt 0 ]; then
    size=$(($size * -1))
    echo -n "-"
  fi
  numfmt --to=iec --format="%.2f" $size
}

table_filter=${1:-"."}
shift

export PGHOST=$POSTGRES_HOST
export PGPORT=$POSTGRES_PORT
export PGDATABASE=$POSTGRES_DB
export PGUSER=$POSTGRES_USER
export PGPASSWORD=$POSTGRES_PASSWORD

set -u -e

psql_command="psql -t -c"
tables=$($psql_command "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public';" | grep $table_filter | xargs)
echo "Tables ($(echo $tables | wc -w)): $tables"

total_saved=0
for table in $tables; do
  table_size=$($psql_command "SELECT pg_total_relation_size('public.$table');" | xargs)
  disk_free_size=$(df -B1 / | tail -1 | awk '{print $4}')
  threshold_size=$(echo "($disk_free_size * 0.8)/1" | bc | xargs)
  echo
  date
  echo "Table $table size: $(human_readable_size $table_size)"
  echo "Disk free: $(human_readable_size $disk_free_size), threshold size (80%): $(human_readable_size $threshold_size)"
  if [ $table_size -gt $threshold_size ]; then
    echo "Skipping table $table because it is too big, table size = $(human_readable_size $table_size)"
    indices=$($psql_command "SELECT indexname FROM pg_indexes WHERE tablename='$table';")
    for index in $indices; do
      index_size=$($psql_command "SELECT pg_total_relation_size('public.$index');" | xargs)
      if [ $index_size -gt $threshold_size ]; then
        echo "Skipping index $index because it is too big, index size = $(human_readable_size $index_size)"
      else
        pg_repack --index $index
      fi
    done
  else
    echo "Repacking (cluster) table $table"
    pg_repack --table $table
    echo "Repacking (vacuum full) table $table"
    pg_repack --table $table --no-order
  fi
  new_table_size=$($psql_command "SELECT pg_total_relation_size('public.$table');" | xargs)
  echo "Table $table new size: $(human_readable_size $new_table_size), saved $(human_readable_size $(($table_size - $new_table_size)))"
  total_saved=$(($total_saved + $table_size - $new_table_size))
done
echo "Total saved: $(human_readable_size $total_saved)"
echo
date
