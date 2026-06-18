#!/usr/bin/env bash
# Run the background DAEMON — the always-on, no-LLM layer (Telegram receiver + cron
# ticker + optional supervision trigger) under a restart-on-crash loop. Point a
# systemd unit or `nohup ... &` at this. The ORCHESTRATOR is separate: open Claude
# Code in this repo and run `/loop agent autopilot`.
set -euo pipefail
cd "$(dirname "$0")/.."
while true; do
  agent daemon || echo "agent daemon exited ($?); restarting in 5s"
  sleep 5
done
