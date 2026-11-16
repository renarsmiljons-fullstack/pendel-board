#!/usr/bin/env bash
# Shows the board full screen in Chromium. Run by pendel-kiosk.service, which starts it
# again whenever Chromium exits, for example after a crash.
#
# Settings come from ~/.config/pendel-board/kiosk.env, written by setup.sh:
#   SCALE  zoom, so the board is laid out for a 600-pixel-tall screen
#   PORT   port of the local web server
set -uo pipefail

CONF="$HOME/.config/pendel-board/kiosk.env"
[ -f "$CONF" ] && . "$CONF"
SCALE="${SCALE:-1}"
PORT="${PORT:-8080}"

# The service starts at boot, before the desktop: wait for its display
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
until [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]; do sleep 2; done

CHROMIUM="$(command -v chromium || command -v chromium-browser)"
# --ozone-platform=wayland: the desktop runs on Wayland. Left to guess, Chromium looks for
#   an X11 display, finds none and quits.
# --password-store=basic: skips the keyring, whose password prompt needs a keyboard.
exec "$CHROMIUM" --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
  --incognito --check-for-update-interval=31536000 --password-store=basic \
  --force-device-scale-factor="$SCALE" --ozone-platform=wayland \
  "http://127.0.0.1:$PORT/"
