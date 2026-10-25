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
if ! command -v kpackagetool6 >/dev/null 2>&1; then
    echo "kpackagetool6 is required (KDE Plasma 6)." >&2
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

mkdir -p "${LIB_DIR}" "${BIN_DIR}" "${ICON_DIR}" "${UNIT_DIR}" "${PLASMOID_DIR}"
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

install -m 0644 "${ROOT}/plasma/${APP_ID}/contents/icons/quota-grid.svg" "${ICON_DIR}/quota-grid.svg"

if kpackagetool6 --type Plasma/Applet --list 2>/dev/null | grep -qx "${APP_ID}"; then
    kpackagetool6 --type Plasma/Applet --upgrade "${ROOT}/plasma/${APP_ID}"
else
    kpackagetool6 --type Plasma/Applet --install "${ROOT}/plasma/${APP_ID}"
fi

install -m 0644 "${ROOT}/systemd/quota-manager.service" "${UNIT_DIR}/quota-manager.service"
systemctl --user daemon-reload
if [[ "${START_SERVICE}" -eq 1 ]]; then
    systemctl --user enable quota-manager.service >/dev/null
    systemctl --user restart quota-manager.service
else
    echo "Service installation skipped (--no-service)."
fi

if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
fi

if [[ "${ADD_TO_PANEL}" -eq 1 ]] && command -v qdbus6 >/dev/null 2>&1; then
    APPLETSRC="${CONFIG_HOME}/plasma-org.kde.plasma.desktop-appletsrc"
    if ! grep -qs "plugin=${APP_ID}" "${APPLETSRC}"; then
        qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
            "var p = panels()[0]; if (p) { p.addWidget('${APP_ID}'); }" >/dev/null || true
    fi
fi

echo "Quota Grid installed."
echo "  widget:  ${APP_ID}"
if [[ "${START_SERVICE}" -eq 1 ]]; then
    echo "  service: systemctl --user status quota-manager"
fi
echo "  check:   quota-manager doctor"
if [[ "${ADD_TO_PANEL}" -eq 1 ]]; then
    echo "The widget is available in the Plasma panel."
else
    echo "Add the widget from the Plasma widget chooser, or run:"
    echo "  ./install.sh --add-to-panel"
fi
