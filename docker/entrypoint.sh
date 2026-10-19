#!/usr/bin/env bash
set -e

source /opt/ros/humble/setup.bash
if [ -f /opt/rds2p/install/setup.bash ]; then
  source /opt/rds2p/install/setup.bash
fi

for d in /opt/rds2p/install/*/lib; do
  if [ -d "$d" ]; then
    LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}$d"
  fi
done
export LD_LIBRARY_PATH

if [ "$#" -eq 1 ]; then
  exec bash -c "$1"
fi
exec "$@"
