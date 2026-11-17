#!/usr/bin/env bash
# Pulls the latest tested version of the board. Run by pendel-listen.service when GitHub
# has a new commit on `stable`, and every 10 minutes by pendel-update.timer as a backup.
# Set FORCE=1 to update while the screen is off.
# Only the `stable` branch is used; CI moves it forward after all tests pass.
# The open page notices the new web/version.txt within 30 seconds and reloads itself.
set -euo pipefail

DIR="${1:?usage: update.sh <repo dir> [branch]}"
BRANCH="${2:-stable}"
cd "$DIR"

# While the screen is off, nothing needs the newest version: skip asking GitHub.
# The board wakes at 06:15 or on a tap, and the next check after that updates it.
screen_off() {
  curl -s --max-time 2 "http://127.0.0.1:${PORT:-8080}/screen" | grep -q '"on": false'
}
if [ -z "${FORCE:-}" ] && screen_off; then
  exit 0
fi

# The listener and the timer can start at the same moment: run one at a time
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/pendel-update.lock"
flock 9

git fetch --quiet origin "$BRANCH"
old="$(git rev-parse HEAD)"
if [ "$old" = "$(git rev-parse "origin/$BRANCH")" ]; then
  exit 0
fi

git reset --quiet --hard "origin/$BRANCH"
git rev-parse --short HEAD > web/version.txt
echo "Updated to $(cat web/version.txt)"

# The page reloads itself, but the Pi's own services run their old code until restarted.
# --no-block: this script may run inside pendel-listen, which the restart stops.
if ! git diff --quiet "$old" HEAD -- pi/server.py pi/listen.sh; then
  systemctl --user --no-block restart pendel-web.service pendel-listen.service || true
fi
