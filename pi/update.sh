#!/usr/bin/env bash
# Pulls the latest tested version of the board. Run every 10 minutes by pendel-update.timer.
# Only the `stable` branch is used; CI moves it forward after all tests pass.
# The open page notices the new web/version.txt within 5 minutes and reloads itself.
set -euo pipefail

DIR="${1:?usage: update.sh <repo dir> [branch]}"
BRANCH="${2:-stable}"
cd "$DIR"

git fetch --quiet origin "$BRANCH"
if [ "$(git rev-parse HEAD)" = "$(git rev-parse "origin/$BRANCH")" ]; then
  exit 0
fi

git reset --quiet --hard "origin/$BRANCH"
git rev-parse --short HEAD > web/version.txt
echo "Updated to $(cat web/version.txt)"
