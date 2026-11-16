#!/usr/bin/env bash
# One-time setup for the departure board on a Raspberry Pi running Raspberry Pi OS (desktop).
#
# Usage (on the Pi, as the normal desktop user, not root):
#   curl -fsSL https://raw.githubusercontent.com/renarsmiljons-fullstack/pendel-board/stable/pi/setup.sh | bash
#
# What it does:
#   1. Installs git, Python 3 and Chromium if they are missing.
#   2. Clones the repo's `stable` branch to ~/pendel-board.
#   3. Runs a web server that only the Pi itself can reach (127.0.0.1:8080).
#   4. Logs in to the desktop automatically and opens the board full screen.
#   5. Updates to the latest tested version as soon as GitHub sends a message (if NTFY_TOPIC
#      is set), and checks GitHub every 10 minutes as a backup.
#   6. Turns off screen blanking, so the board decides when the screen is dark.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/renarsmiljons-fullstack/pendel-board.git}"
# Private ntfy.sh topic for instant updates. It must match the NTFY_TOPIC secret on GitHub.
# Leave it unset to keep a topic saved by an earlier run, or to use only the 10-minute check.
NTFY_TOPIC="${NTFY_TOPIC:-}"
BRANCH="${BRANCH:-stable}"
DIR="$HOME/pendel-board"
PORT=8080

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this as your normal user, not with sudo." >&2
  exit 1
fi

echo "==> Installing packages"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3
if ! command -v chromium >/dev/null && ! command -v chromium-browser >/dev/null; then
  sudo apt-get install -y -qq chromium || sudo apt-get install -y -qq chromium-browser
fi
CHROMIUM="$(command -v chromium || command -v chromium-browser)"

echo "==> Getting the board ($BRANCH branch)"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch --quiet origin "$BRANCH"
  git -C "$DIR" checkout --quiet "$BRANCH"
  git -C "$DIR" reset --quiet --hard "origin/$BRANCH"
else
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$DIR"
fi
git -C "$DIR" rev-parse --short HEAD > "$DIR/web/version.txt"

echo "==> Installing services"
mkdir -p "$HOME/.config/systemd/user"
if [ -n "$NTFY_TOPIC" ]; then
  mkdir -p "$HOME/.config/pendel-board"
  echo "$NTFY_TOPIC" > "$HOME/.config/pendel-board/ntfy-topic"
  chmod 600 "$HOME/.config/pendel-board/ntfy-topic"
fi
for unit in pendel-web.service pendel-update.service pendel-update.timer pendel-listen.service; do
  sed -e "s|@DIR@|$DIR|g" -e "s|@PORT@|$PORT|g" -e "s|@BRANCH@|$BRANCH|g" \
    "$DIR/pi/$unit" > "$HOME/.config/systemd/user/$unit"
done
chmod +x "$DIR/pi/update.sh"
systemctl --user daemon-reload
systemctl --user enable --now pendel-web.service pendel-update.timer pendel-listen.service
systemctl --user restart pendel-listen.service   # pick up a new topic
# Keep user services running without anyone logged in over SSH
sudo loginctl enable-linger "$USER"

echo "==> Opening the board full screen at login"
# Current Raspberry Pi OS runs the labwc desktop on Wayland. Chromium must be told: when it guesses,
# it looks for an X11 display, finds none and quits.
if [ -d /etc/xdg/labwc ]; then OZONE="--ozone-platform=wayland"; else OZONE="--ozone-platform-hint=auto"; fi
# The board is laid out for a 600-pixel-tall screen. Small panels often report 1920x1080 and shrink
# the picture, so zoom Chromium by (short side / 600). Set BOARD_SCALE to override.
SCALE=1
if command -v wlr-randr >/dev/null; then
  SIZE=$(WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}" XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" \
    wlr-randr 2>/dev/null | awk '/current/ {print $1; exit}')
  if [ -n "$SIZE" ]; then
    SCALE=$(echo "$SIZE" | awk -Fx '{s = ($1 < $2 ? $1 : $2) / 600; if (s < 1) s = 1; printf "%.2f", s}')
  fi
fi
SCALE="${BOARD_SCALE:-$SCALE}"
echo "    zoom: $SCALE"
KIOSK="$CHROMIUM --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble --incognito --check-for-update-interval=31536000 --password-store=basic --force-device-scale-factor=$SCALE $OZONE http://127.0.0.1:$PORT/"
if [ -d /etc/xdg/labwc ]; then
  # Current Raspberry Pi OS desktop (labwc): start the board from labwc's own autostart file
  mkdir -p "$HOME/.config/labwc"
  touch "$HOME/.config/labwc/autostart"
  sed -i '/127.0.0.1:[0-9]*\//d' "$HOME/.config/labwc/autostart"   # drop the line from an earlier run
  echo "$KIOSK &" >> "$HOME/.config/labwc/autostart"
  rm -f "$HOME/.config/autostart/pendel-board.desktop"
else
  # Older desktops: the standard XDG autostart folder
  mkdir -p "$HOME/.config/autostart"
  cat > "$HOME/.config/autostart/pendel-board.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Departure board
Exec=$KIOSK
X-GNOME-Autostart-enabled=true
EOF
fi

echo "==> Logging in to the desktop automatically"
if command -v raspi-config >/dev/null; then
  sudo raspi-config nonint do_boot_behaviour B4 || true
fi

echo "==> Turning off screen blanking"
if command -v raspi-config >/dev/null; then
  sudo raspi-config nonint do_blanking 1 || true
fi

echo
echo "Done. Reboot to start the board:  sudo reboot"
echo "Check the web server:              systemctl --user status pendel-web"
echo "Check updates:                     journalctl --user -u pendel-update -n 20"
