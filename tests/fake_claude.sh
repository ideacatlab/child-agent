#!/usr/bin/env bash
# A stand-in for the `claude` CLI used by the fleet tests — no tokens, no network.
# It mimics `claude -p "<task>" --output-format json ...` by printing one JSON
# result object. Knobs (via env): FAKE_CLAUDE_FAIL=1 -> error result + exit 1;
# FAKE_CLAUDE_SLEEP=<secs> -> sleep first (to exercise timeouts).
set -euo pipefail

task=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-p" ]; then task="$arg"; fi
  prev="$arg"
done

if [ -n "${FAKE_CLAUDE_SLEEP:-}" ]; then sleep "$FAKE_CLAUDE_SLEEP"; fi

if [ "${FAKE_CLAUDE_FAIL:-0}" = "1" ]; then
  printf '{"type":"result","is_error":true,"result":"fake failure for: %s","duration_ms":1}\n' "$task"
  exit 1
fi

printf '{"type":"result","subtype":"success","is_error":false,"result":"fake worker handled: %s","session_id":"fake","duration_ms":1}\n' "$task"
