#!/usr/bin/env bash
set -euo pipefail
rule=(-i br-8c9367a25552 -s 172.19.0.0/16 -d 172.19.0.1 -p tcp --dport 8787 -j ACCEPT)
case "${1:-start}" in
  start)
    iptables -C INPUT "${rule[@]}" 2>/dev/null || iptables -I INPUT 1 "${rule[@]}"
    ;;
  stop)
    iptables -C INPUT "${rule[@]}" 2>/dev/null && iptables -D INPUT "${rule[@]}" || true
    ;;
  *)
    exit 2
    ;;
esac