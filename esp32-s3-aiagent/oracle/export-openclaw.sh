#!/usr/bin/env bash
set -euo pipefail
umask 077
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
docker inspect big-bear-openclaw > "$stage/container.json"
image_id=$(docker inspect -f '{{.Image}}' big-bear-openclaw)
docker image inspect "$image_id" > "$stage/image.json"
docker stop --time 30 big-bear-openclaw
tar -C /DATA/AppData/big-bear-openclaw -czf /tmp/openclaw-migration.tar.gz config workspace
tar -C "$stage" -czf /tmp/openclaw-metadata.tar.gz container.json image.json
chmod 600 /tmp/openclaw-migration.tar.gz /tmp/openclaw-metadata.tar.gz
docker inspect -f 'TV OpenClaw running={{.State.Running}}' big-bear-openclaw
ls -lh /tmp/openclaw-migration.tar.gz /tmp/openclaw-metadata.tar.gz