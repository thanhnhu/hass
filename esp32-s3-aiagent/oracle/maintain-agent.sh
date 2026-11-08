#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/agent-maintenance"
exec "$HOME/.local/bin/claude" --permission-mode plan \
  'Review the local router and OpenClaw model profile for latency, prompt size, and redundant model calls. Do not read credentials, change live services, or install anything. Preserve Home Assistant local intents, music playback and gold-price source timestamps. Propose measurable improvements and focused regression checks before making changes.'