#!/usr/bin/env bash
# Installs (or re-installs/migrates) the printer client on Raspberry Pi OS / Debian / Ubuntu.
#
# Fresh box:
#   curl -fsSL https://raw.githubusercontent.com/drbugspopcorn/mqtt-printer-client/master/app/install.sh \
#       | sudo bash -s -- --broker docker-host-esxi.local --name packing-1
#
# Existing checkout (safe to re-run, keeps .env):
#   sudo ./app/install.sh
set -euo pipefail

REPO_URL="https://github.com/drbugspopcorn/mqtt-printer-client.git"
SERVICE=printer-client
BROKER=""
PORT=""
NAME=""
INSTALL_DIR=""
RUN_USER="${SUDO_USER:-}"
REMOTE_CUPS=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --broker) BROKER="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --name) NAME="$2"; shift 2 ;;
        --dir) INSTALL_DIR="$2"; shift 2 ;;
        --user) RUN_USER="$2"; shift 2 ;;
        --no-remote-cups) REMOTE_CUPS=0; shift ;;
        *) echo "Unknown option $1"; exit 1 ;;
    esac
done

[[ $EUID -eq 0 ]] || { echo "Run with sudo"; exit 1; }
[[ -n "$RUN_USER" && "$RUN_USER" != root ]] || { echo "Can't tell which user to run as - pass --user"; exit 1; }
RUN_HOME=$(getent passwd "$RUN_USER" | cut -d: -f6)
as_user() { sudo -u "$RUN_USER" -H "$@"; }

apt_help() {
    echo
    echo "Couldn't install: $MISSING"
    if grep -qs 'buster' /etc/os-release; then
        cat <<'EOF'
This is Raspbian buster, which is end-of-life - its package servers have moved. Point apt at the archive, then re-run:

    sudo sed -i 's|raspbian.raspberrypi.org|legacy.raspbian.org|' /etc/apt/sources.list
    sudo sed -i '/buster-backports/s/^/#/' /etc/apt/sources.list /etc/apt/sources.list.d/*.list
    sudo apt-get update --allow-releaseinfo-change

(Longer term, reflash with a current Raspberry Pi OS.)
EOF
    fi
    exit 1
}

echo "==> Packages"
PACKAGES="git cups cups-client libcups2-dev python3 python3-venv python3-dev gcc"
# only touch apt if something's missing - old boxes often can't reach their package servers any more
MISSING=$(for p in $PACKAGES; do dpkg -s "$p" >/dev/null 2>&1 || printf '%s ' "$p"; done)
if [[ -n "$MISSING" ]]; then
    apt-get update -q || echo "apt-get update had errors, trying the install anyway"
    # shellcheck disable=SC2086
    apt-get install -y -q $MISSING || apt_help
else
    echo "    all present"
fi

# work out where the repo is: the checkout we're running from, --dir, or clone a fresh one
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [[ -z "$INSTALL_DIR" && -f "$SCRIPT_DIR/printer_client.py" ]]; then
    INSTALL_DIR="$(dirname "$SCRIPT_DIR")"
fi
INSTALL_DIR="${INSTALL_DIR:-$RUN_HOME/mqtt-printer-client}"
if [[ ! -d "$INSTALL_DIR/.git" ]]; then
    echo "==> Cloning into $INSTALL_DIR"
    as_user git clone "$REPO_URL" "$INSTALL_DIR"
fi
APP_DIR="$INSTALL_DIR/app"
chown -R "$RUN_USER": "$INSTALL_DIR"
as_user git -C "$INSTALL_DIR" config --replace-all core.fileMode false

echo "==> Python environment"
as_user python3 -m venv "$INSTALL_DIR/.venv"
# the pip bundled with older Pythons (buster has 3.7) struggles with current packages
as_user "$INSTALL_DIR/.venv/bin/pip" install -q --disable-pip-version-check --upgrade pip
as_user "$INSTALL_DIR/.venv/bin/pip" install -q --disable-pip-version-check -r "$APP_DIR/requirements.common.txt"

if [[ ! -f "$APP_DIR/.env" && -f "$INSTALL_DIR/.env" ]]; then
    # older installs kept .env at the top of the checkout - keep its name and broker so OMS printer choices still work
    echo "==> Moving $INSTALL_DIR/.env to $APP_DIR/.env"
    as_user cp "$INSTALL_DIR/.env" "$APP_DIR/.env"
fi
if [[ ! -f "$APP_DIR/.env" ]]; then
    echo "==> Creating $APP_DIR/.env"
    as_user cp "$APP_DIR/example.env" "$APP_DIR/.env"
    sed -i "s/^CLIENT_NAME=.*/CLIENT_NAME=${NAME:-$(hostname -s)}/" "$APP_DIR/.env"
fi
[[ -n "$NAME" ]] && sed -i "s/^CLIENT_NAME=.*/CLIENT_NAME=$NAME/" "$APP_DIR/.env"
[[ -n "$BROKER" ]] && sed -i "s/^MQTT_BROKER_ADDRESS=.*/MQTT_BROKER_ADDRESS=$BROKER/" "$APP_DIR/.env"
[[ -n "$PORT" ]] && sed -i "s/^MQTT_BROKER_PORT=.*/MQTT_BROKER_PORT=$PORT/" "$APP_DIR/.env"
as_user mkdir -p "$APP_DIR/docs_tmp"

echo "==> CUPS"
usermod -a -G lpadmin "$RUN_USER"
systemctl enable --now cups
if [[ $REMOTE_CUPS -eq 1 ]]; then
    # lets you use http://<host>.local:631 from another machine when the fleet page isn't enough
    cupsctl --remote-admin --remote-any
fi

echo "==> Allowing $RUN_USER to reboot from the fleet page"
SUDOERS=/etc/sudoers.d/$SERVICE
echo "$RUN_USER ALL=(root) NOPASSWD: /usr/bin/systemctl reboot, /bin/systemctl reboot" > "$SUDOERS.tmp"
chmod 440 "$SUDOERS.tmp"
visudo -cf "$SUDOERS.tmp" >/dev/null && mv "$SUDOERS.tmp" "$SUDOERS"

echo "==> systemd service"
# older installs put the unit in /lib with a hardcoded pi user
if [[ -f /lib/systemd/system/$SERVICE.service ]]; then
    systemctl disable "$SERVICE" 2>/dev/null || true
    rm -f /lib/systemd/system/$SERVICE.service
fi
sed -e "s|@USER@|$RUN_USER|g" -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@PYTHON@|$INSTALL_DIR/.venv/bin/python|g" \
    "$APP_DIR/printer-client.service" > /etc/systemd/system/$SERVICE.service
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

echo
echo "Installed.  Config: $APP_DIR/.env"
grep -E '^(CLIENT_NAME|MQTT_BROKER_ADDRESS|MQTT_BROKER_PORT)=' "$APP_DIR/.env"
echo "Logs: journalctl -u $SERVICE -f"
