#!/usr/bin/env bash
# Prints the chat ID and topic (message_thread_id) of recent messages the bot can see.
#
# Usage (token is read from your own shell, never pasted anywhere else):
#   read -rs TELEGRAM_BOT_TOKEN && export TELEGRAM_BOT_TOKEN
#   ./scripts/get-telegram-ids.sh
#
# Before running: post a message INSIDE the "Notification" topic of your group
# (for example "ping"), so the bot has a fresh update to report.
# Requires: curl, jq
set -euo pipefail

: "${TELEGRAM_BOT_TOKEN:?Set TELEGRAM_BOT_TOKEN first (see header of this script)}"

resp="$(curl -sS --max-time 20 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates")"

if [[ "$(jq -r '.ok' <<<"$resp")" != "true" ]]; then
  echo "Telegram error: $(jq -r '.description // "unknown"' <<<"$resp")" >&2
  exit 1
fi

count="$(jq '.result | length' <<<"$resp")"
if [[ "$count" == "0" ]]; then
  cat >&2 <<'MSG'
No updates found. Check that:
  1. The bot is a member of the group.
  2. You posted a NEW message in the Notification topic after adding the bot.
  3. Bot privacy mode is off, or your message mentions the bot / is a /command
     (BotFather > /mybots > your bot > Bot Settings > Group Privacy > Turn off).
  4. No webhook is set for this bot (run: curl https://api.telegram.org/bot<TOKEN>/deleteWebhook).
MSG
  exit 1
fi

echo "Recent messages the bot can see:"
echo
jq -r '
  [.result[] | (.message // .edited_message // .channel_post // empty)
   | select(.chat.type == "supergroup" or .chat.type == "group")]
  | unique_by([.chat.id, (.message_thread_id // 0)])
  | .[]
  | "chat title : \(.chat.title)\n"
    + "chat id    : \(.chat.id)        -> TELEGRAM_CHAT_ID\n"
    + "thread id  : \(.message_thread_id // "none (General topic or topics disabled)")        -> TELEGRAM_THREAD_ID\n"
    + "topic name : \(.reply_to_message.forum_topic_created.name // "(only shown on the first message of a topic)")\n"
    + "sample text: \((.text // "")[0:60])\n"
' <<<"$resp"

echo "Pick the entry whose sample text is the message you posted in the Notification topic."
