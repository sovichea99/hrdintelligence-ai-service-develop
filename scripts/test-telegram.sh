#!/usr/bin/env bash
# Sends a test message to your Telegram topic, to verify token + chat ID + thread ID
# BEFORE relying on the GitHub workflow.
#
# Usage (values come from your own shell, never pasted into chat):
#   read -rs TELEGRAM_BOT_TOKEN && export TELEGRAM_BOT_TOKEN
#   export TELEGRAM_CHAT_ID="-1001234567890"
#   export TELEGRAM_THREAD_ID="2"
#   ./scripts/test-telegram.sh
#
# Requires: curl, jq
set -euo pipefail

: "${TELEGRAM_BOT_TOKEN:?Set TELEGRAM_BOT_TOKEN}"
: "${TELEGRAM_CHAT_ID:?Set TELEGRAM_CHAT_ID}"

args=(
  --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}"
  --data-urlencode "text=✅ <b>Test notification</b>
If you can read this in the <code>Notification</code> topic, routing works."
  --data-urlencode "parse_mode=HTML"
)
if [[ -n "${TELEGRAM_THREAD_ID:-}" ]]; then
  args+=(--data-urlencode "message_thread_id=${TELEGRAM_THREAD_ID}")
fi

resp="$(curl -sS --max-time 20 -X POST \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" "${args[@]}")"

if [[ "$(jq -r '.ok' <<<"$resp")" == "true" ]]; then
  echo "Sent. Message landed in thread: $(jq -r '.result.message_thread_id // "General / none"' <<<"$resp")"
else
  echo "Telegram error: $(jq -r '.description // "unknown"' <<<"$resp")" >&2
  exit 1
fi
