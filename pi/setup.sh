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
#   4. Opens the board full screen when the desktop starts.
#   5. Checks GitHub every 10 minutes and updates to the latest tested version.
#   6. Turns off screen blanking, so the board decides when the screen is dark.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/renarsmiljons-fullstack/pendel-board.git}"
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
for unit in pendel-web.service pendel-update.service pendel-update.timer; do
  sed -e "s|@DIR@|$DIR|g" -e "s|@PORT@|$PORT|g" -e "s|@BRANCH@|$BRANCH|g" \
    "$DIR/pi/$unit" > "$HOME/.config/systemd/user/$unit"
done
chmod +x "$DIR/pi/update.sh"
systemctl --user daemon-reload
systemctl --user enable --now pendel-web.service pendel-update.timer
# Keep user services running without anyone logged in over SSH
sudo loginctl enable-linger "$USER"

echo "==> Opening the board full screen at login"
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/pendel-board.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Departure board
Exec=$CHROMIUM --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble --incognito --check-for-update-interval=31536000 --ozone-platform-hint=auto http://127.0.0.1:$PORT/
X-GNOME-Autostart-enabled=true
EOF

echo "==> Turning off screen blanking"
if command -v raspi-config >/dev/null; then
  sudo raspi-config nonint do_blanking 1 || true
fi

echo
echo "Done. Reboot to start the board:  sudo reboot"
echo "Check the web server:              systemctl --user status pendel-web"
echo "Check updates:                     journalctl --user -u pendel-update -n 20"
