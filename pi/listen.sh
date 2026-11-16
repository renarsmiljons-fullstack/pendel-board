#!/usr/bin/env bash
# Pulls a new version of the board as soon as GitHub says one is ready.
# Run by pendel-listen.service. The notify workflow sends a message to a private
# ntfy.sh topic after CI passes on main. This script keeps one outgoing connection
# open to that topic and runs update.sh for every message. The Pi accepts no
# incoming connections; pendel-update.timer still checks every 10 minutes as a backup.
#
# The topic name is private: it lives in ~/.config/pendel-board/ntfy-topic on the Pi
# and in the NTFY_TOPIC secret on GitHub, never in this public repo.
set -uo pipefail

DIR="${1:?usage: listen.sh <repo dir> [branch]}"
BRANCH="${2:-stable}"
TOPIC_FILE="${TOPIC_FILE:-$HOME/.config/pendel-board/ntfy-topic}"
NTFY_URL="${NTFY_URL:-https://ntfy.sh}"

if [ ! -s "$TOPIC_FILE" ]; then
  echo "No topic in $TOPIC_FILE: push updates are off, the 10-minute check still runs."
  exit 0
fi
TOPIC="$(tr -d '[:space:]' < "$TOPIC_FILE")"

while true; do
  # /raw streams one line per message; ntfy also sends empty keepalive lines
  while IFS= read -r message; do
    [ -z "$message" ] && continue
    echo "Notified: $message"
    bash "$DIR/pi/update.sh" "$DIR" "$BRANCH" || echo "Update failed; the timer will retry."
  done < <(curl -sfN --max-time 3600 "$NTFY_URL/$TOPIC/raw")
  sleep 10   # connection dropped or timed out: reconnect
done
