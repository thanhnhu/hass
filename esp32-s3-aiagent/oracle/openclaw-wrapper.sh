#!/bin/sh
if [ "$#" -eq 0 ]; then
  set -- tui
fi
if [ -t 0 ] && [ -t 1 ]; then
  exec sudo -n docker exec -it oracle-openclaw node dist/index.js "$@"
fi
exec sudo -n docker exec -i oracle-openclaw node dist/index.js "$@"