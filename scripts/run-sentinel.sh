#!/usr/bin/env bash
# Run the scion SENTINEL — the always-on, no-LLM layer (Telegram receiver + cron
# ticker) under a restart-on-crash loop. Point a systemd unit or `nohup ... &` at
# this. The BRAIN is separate: open Claude Code and run `/loop scion autopilot`.
set -euo pipefail
cd "$(dirname "$0")/.."
while true; do
  scion sentinel || echo "scion sentinel exited ($?); restarting in 5s"
  sleep 5
done
