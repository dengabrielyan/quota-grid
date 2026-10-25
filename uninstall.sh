#!/usr/bin/env bash
set -euo pipefail

PURGE=0
for arg in "$@"; do
    case "$arg" in
        --purge) PURGE=1 ;;
        -h|--help)
            echo "Usage: ./uninstall.sh [--purge]"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg" >&2
            exit 2
            ;;
    esac
done

DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
STATE_HOME="${XDG_STATE_HOME:-${HOME}/.local/state}"
CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
APP_ID="org.kde.quota-grid"

systemctl --user disable --now quota-manager.service 2>/dev/null || true
rm -f "${CONFIG_HOME}/systemd/user/quota-manager.service"
systemctl --user daemon-reload 2>/dev/null || true

if command -v kpackagetool6 >/dev/null 2>&1; then
    kpackagetool6 --type Plasma/Applet --remove "${APP_ID}" 2>/dev/null || true
fi

rm -f "${DATA_HOME}/applications/quota-grid.desktop"
rm -f "${CONFIG_HOME}/autostart/quota-grid-daemon.desktop"
rm -rf "${HOME}/.local/lib/quota-manager"
rm -f "${HOME}/.local/bin/quota-manager" "${HOME}/.local/bin/quota-grid"
rm -f "${DATA_HOME}/icons/hicolor/scalable/apps/quota-grid.svg"

if [[ "${PURGE}" -eq 1 ]]; then
    rm -rf "${DATA_HOME}/quota-manager" "${STATE_HOME}/quota-manager" "${CONFIG_HOME}/quota-manager"
    echo "Quota Grid removed, including cached data."
else
    echo "Quota Grid removed. Cached quota data was kept (use --purge to remove it)."
fi
