#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_ID="org.kde.quota-grid"
PREFIX="${HOME}/.local"
LIB_DIR="${PREFIX}/lib/quota-manager"
BIN_DIR="${PREFIX}/bin"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
STATE_HOME="${XDG_STATE_HOME:-${HOME}/.local/state}"
CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
ICON_DIR="${DATA_HOME}/icons/hicolor/scalable/apps"
APPLICATIONS_DIR="${DATA_HOME}/applications"
AUTOSTART_DIR="${CONFIG_HOME}/autostart"
UNIT_DIR="${CONFIG_HOME}/systemd/user"
PLASMOID_DIR="${DATA_HOME}/plasma/plasmoids"
ADD_TO_PANEL=0
START_SERVICE=1

for arg in "$@"; do
    case "$arg" in
        --add-to-panel) ADD_TO_PANEL=1 ;;
        --no-service) START_SERVICE=0 ;;
        -h|--help)
            echo "Usage: ./install.sh [--add-to-panel] [--no-service]"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg" >&2
            exit 2
            ;;
    esac
done

if [[ ! -x /usr/bin/python3 ]]; then
    echo "Python 3 is required." >&2
    exit 1
fi
if ! /usr/bin/python3 - <<'PY'
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
except Exception:
    raise SystemExit(1)
PY
then
    echo "Warning: python3-cryptography is not installed; ZCode quotas will be unavailable." >&2
    echo "Install the cryptography package for your distribution (for example, python3-cryptography on Debian/Ubuntu/Fedora or python-cryptography on Arch)." >&2
fi

HAS_PLASMA=0
if command -v kpackagetool6 >/dev/null 2>&1; then
    HAS_PLASMA=1
fi
HAS_SYSTEMD=0
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    HAS_SYSTEMD=1
fi

mkdir -p "${LIB_DIR}" "${BIN_DIR}" "${ICON_DIR}" "${APPLICATIONS_DIR}" "${AUTOSTART_DIR}"
mkdir -p "${UNIT_DIR}" "${PLASMOID_DIR}"
mkdir -p "${STATE_HOME}/quota-manager" "${DATA_HOME}/quota-manager" "${CONFIG_HOME}/quota-manager"
chmod 700 "${STATE_HOME}/quota-manager" "${DATA_HOME}/quota-manager" "${CONFIG_HOME}/quota-manager"
if [[ ! -f "${CONFIG_HOME}/quota-manager/config.json" ]]; then
    cat > "${CONFIG_HOME}/quota-manager/config.json" <<'JSON'
{
  "refresh_interval_seconds": 300,
  "notifications": true
}
JSON
    chmod 600 "${CONFIG_HOME}/quota-manager/config.json"
fi

rm -rf "${LIB_DIR}/quota_manager"
cp -a "${ROOT}/quota_manager" "${LIB_DIR}/quota_manager"
find "${LIB_DIR}/quota_manager" -type d -name __pycache__ -prune -exec rm -rf {} +

cat > "${BIN_DIR}/quota-manager" <<'WRAPPER'
#!/bin/sh
set -eu
export PYTHONPATH="$HOME/.local/lib/quota-manager${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m quota_manager "$@"
WRAPPER
chmod 755 "${BIN_DIR}/quota-manager"
ln -sf "${BIN_DIR}/quota-manager" "${BIN_DIR}/quota-grid"

install -m 0644 "${ROOT}/plasma/${APP_ID}/contents/icons/quota-grid.svg" "${ICON_DIR}/quota-grid.svg"

cat > "${APPLICATIONS_DIR}/quota-grid.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Quota Grid
Name[ru]=Quota Grid
Comment=AI quota limits for Claude Code, Codex and ZCode
Comment[ru]=Лимиты Claude Code, Codex и ZCode
Exec="${BIN_DIR}/quota-manager" ui
Icon=quota-grid
Terminal=false
Categories=Utility;
Keywords=AI;quota;Claude;Codex;ZCode;
StartupNotify=true
EOF
chmod 644 "${APPLICATIONS_DIR}/quota-grid.desktop"

if [[ "${HAS_PLASMA}" -eq 1 ]]; then
    if kpackagetool6 --type Plasma/Applet --list 2>/dev/null | grep -qx "${APP_ID}"; then
        kpackagetool6 --type Plasma/Applet --upgrade "${ROOT}/plasma/${APP_ID}"
    else
        kpackagetool6 --type Plasma/Applet --install "${ROOT}/plasma/${APP_ID}"
    fi
else
    echo "KDE Plasma 6 was not detected; the web dashboard will be installed without the panel widget."
fi

rm -f "${AUTOSTART_DIR}/quota-grid-daemon.desktop"
if [[ "${START_SERVICE}" -eq 1 ]]; then
    if [[ "${HAS_SYSTEMD}" -eq 1 ]]; then
        install -m 0644 "${ROOT}/systemd/quota-manager.service" "${UNIT_DIR}/quota-manager.service"
        systemctl --user daemon-reload 2>/dev/null || true
        systemctl --user enable quota-manager.service >/dev/null
        systemctl --user restart quota-manager.service
    else
        cat > "${AUTOSTART_DIR}/quota-grid-daemon.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Quota Grid daemon
Comment=Background quota collector
Exec="${BIN_DIR}/quota-manager" daemon
Icon=quota-grid
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
        chmod 644 "${AUTOSTART_DIR}/quota-grid-daemon.desktop"
        if ! pgrep -f "${BIN_DIR}/quota-manager daemon" >/dev/null 2>&1; then
            nohup "${BIN_DIR}/quota-manager" daemon >/dev/null 2>&1 &
        fi
        echo "Started the background collector through XDG autostart (systemd is not available)."
    fi
else
    if [[ "${HAS_SYSTEMD}" -eq 1 ]]; then
        systemctl --user disable --now quota-manager.service 2>/dev/null || true
    fi
    rm -f "${UNIT_DIR}/quota-manager.service"
    echo "Background service installation skipped (--no-service)."
fi

if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
fi

if [[ "${ADD_TO_PANEL}" -eq 1 ]]; then
    if [[ "${HAS_PLASMA}" -eq 1 ]] && command -v qdbus6 >/dev/null 2>&1; then
        APPLETSRC="${CONFIG_HOME}/plasma-org.kde.plasma.desktop-appletsrc"
        if ! grep -qs "plugin=${APP_ID}" "${APPLETSRC}"; then
            qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
                "var p = panels()[0]; if (p) { p.addWidget('${APP_ID}'); }" >/dev/null || true
        fi
    else
        echo "The panel widget can only be added on KDE Plasma 6."
    fi
fi

echo "Quota Grid installed."
echo "  app:     Quota Grid in the application menu (web dashboard)"
echo "  cli:     quota-manager"
if [[ "${HAS_PLASMA}" -eq 1 ]]; then
    echo "  widget:  ${APP_ID}"
fi
if [[ "${START_SERVICE}" -eq 1 ]]; then
    if [[ "${HAS_SYSTEMD}" -eq 1 ]]; then
        echo "  service: systemctl --user status quota-manager"
    else
        echo "  daemon:  ${AUTOSTART_DIR}/quota-grid-daemon.desktop"
    fi
fi
echo "  check:   quota-manager doctor"
if [[ "${ADD_TO_PANEL}" -ne 1 ]] && [[ "${HAS_PLASMA}" -eq 1 ]]; then
    echo "Add the widget from the Plasma widget chooser, or run: ./install.sh --add-to-panel"
fi
