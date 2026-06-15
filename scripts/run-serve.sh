#!/usr/bin/env bash
# Run the scion autonomy stack (worker + scheduler + Telegram bot) under a
# restart-on-crash loop. Point a systemd unit or `nohup ... &` at this.
set -euo pipefail
cd "$(dirname "$0")/.."
while true; do
  scion serve || echo "scion serve exited ($?); restarting in 5s"
  sleep 5
done
