#!/usr/bin/env bash
# Pulls the latest tested version of the board. Run by pendel-listen.service as soon as
# GitHub sends a message, and every 10 minutes by pendel-update.timer as a backup.
# Only the `stable` branch is used; CI moves it forward after all tests pass.
# The open page notices the new web/version.txt within 30 seconds and reloads itself.
set -euo pipefail

DIR="${1:?usage: update.sh <repo dir> [branch]}"
BRANCH="${2:-stable}"
cd "$DIR"

# The listener and the timer can start at the same moment: run one at a time
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/pendel-update.lock"
flock 9

git fetch --quiet origin "$BRANCH"
if [ "$(git rev-parse HEAD)" = "$(git rev-parse "origin/$BRANCH")" ]; then
  exit 0
fi

git reset --quiet --hard "origin/$BRANCH"
git rev-parse --short HEAD > web/version.txt
echo "Updated to $(cat web/version.txt)"
