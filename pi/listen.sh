#!/usr/bin/env bash
# Pulls a new version of the board soon after CI moves the `stable` branch.
# Run by pendel-listen.service. Every 30 seconds it asks GitHub which commit `stable`
# points to (`git ls-remote`: one small request, no account or secret), and runs update.sh
# when that commit differs from the one on the Pi. The Pi accepts no incoming connections.
# pendel-update.timer still checks every 10 minutes as a backup.
set -uo pipefail

DIR="${1:?usage: listen.sh <repo dir> [branch]}"
BRANCH="${2:-stable}"
INTERVAL="${INTERVAL:-30}"
cd "$DIR"

while true; do
  remote="$(git ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | cut -f1)"
  if [ -n "$remote" ] && [ "$remote" != "$(git rev-parse HEAD)" ]; then
    echo "New version on $BRANCH: ${remote:0:7}"
    bash "$DIR/pi/update.sh" "$DIR" "$BRANCH" || echo "Update failed; trying again in $INTERVAL seconds."
  fi
  sleep "$INTERVAL"
done
