#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${ROOT}/quota_manager/__init__.py")
OUT_DIR="${ROOT}/dist"
DEB="${OUT_DIR}/quota-grid_${VERSION}_all.deb"
STAGE=$(mktemp -d)
trap 'rm -rf "${STAGE}"' EXIT

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "dpkg-deb is required (install dpkg-dev on Debian/Ubuntu)." >&2
    exit 1
fi
if [[ -z "${VERSION}" ]]; then
    echo "Could not read the version from quota_manager/__init__.py." >&2
    exit 1
fi

install -d "${STAGE}/DEBIAN" "${STAGE}/usr/bin" "${STAGE}/usr/lib/quota-grid"
install -d "${STAGE}/usr/share/applications" "${STAGE}/usr/share/icons/hicolor/scalable/apps"
install -d "${STAGE}/usr/share/doc/quota-grid" "${STAGE}/etc/xdg/autostart"
install -d "${STAGE}/usr/share/plasma/plasmoids"

cp -a "${ROOT}/quota_manager" "${STAGE}/usr/lib/quota-grid/"
find "${STAGE}/usr/lib/quota-grid" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${STAGE}/usr/lib/quota-grid" -type f -name '*.pyc' -delete

cat > "${STAGE}/usr/bin/quota-grid" <<'WRAPPER'
#!/bin/sh
set -eu
export PYTHONPATH="/usr/lib/quota-grid${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m quota_manager "$@"
WRAPPER
chmod 755 "${STAGE}/usr/bin/quota-grid"
ln -s quota-grid "${STAGE}/usr/bin/quota-manager"

install -m 0644 "${ROOT}/plasma/org.kde.quota-grid/contents/icons/quota-grid.svg" \
    "${STAGE}/usr/share/icons/hicolor/scalable/apps/quota-grid.svg"

cat > "${STAGE}/usr/share/applications/quota-grid.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Quota Grid
Name[ru]=Quota Grid
Comment=AI quota limits for Claude Code, Codex and ZCode
Comment[ru]=Лимиты Claude Code, Codex и ZCode
Exec=/usr/bin/quota-manager ui
Icon=quota-grid
Terminal=false
Categories=Utility;
Keywords=AI;quota;Claude;Codex;ZCode;
StartupNotify=true
DESKTOP
chmod 644 "${STAGE}/usr/share/applications/quota-grid.desktop"

cat > "${STAGE}/etc/xdg/autostart/quota-grid-daemon.desktop" <<'AUTOSTART'
[Desktop Entry]
Type=Application
Name=Quota Grid daemon
Comment=Background quota collector
Exec=/usr/bin/quota-manager daemon
Icon=quota-grid
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
AUTOSTART
chmod 644 "${STAGE}/etc/xdg/autostart/quota-grid-daemon.desktop"

cp -a "${ROOT}/plasma/org.kde.quota-grid" "${STAGE}/usr/share/plasma/plasmoids/"
python3 - "${STAGE}/usr/share/plasma/plasmoids/org.kde.quota-grid/contents/ui/main.qml" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = "$HOME/.local/bin/quota-manager"
if text.count(old) != 1:
    raise SystemExit("unexpected applet CLI path in main.qml")
path.write_text(text.replace(old, "/usr/bin/quota-manager"), encoding="utf-8")
PY

cp "${ROOT}/LICENSE" "${STAGE}/usr/share/doc/quota-grid/copyright"
cp "${ROOT}/README.md" "${STAGE}/usr/share/doc/quota-grid/README.md"
cp -a "${ROOT}/docs" "${STAGE}/usr/share/doc/quota-grid/"
gzip -9 -n -c "${ROOT}/LICENSE" > "${STAGE}/usr/share/doc/quota-grid/LICENSE.gz"

INSTALLED_SIZE=$(du -sk "${STAGE}/usr" | cut -f1)
cat > "${STAGE}/DEBIAN/control" <<CONTROL
Package: quota-grid
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: all
Maintainer: Daniel Gabrielyan <290777733+dengabrielyan@users.noreply.github.com>
Installed-Size: ${INSTALLED_SIZE}
Depends: python3 (>= 3.10), libnotify-bin, xdg-utils
Recommends: python3-cryptography, fonts-ibm-plex
Homepage: https://github.com/dengabrielyan/quota-grid
Description: AI quota limits for KDE Plasma and the Linux desktop
 Quota Grid reads existing local sessions of Claude Code, Codex CLI and
 ZCode Desktop, shows five-hour, weekly, daily and bonus limits, refreshes
 them in the background and notifies when a limit window resets.
 .
 It includes a KDE Plasma 6 panel widget and a cross-desktop local web
 dashboard for GNOME, XFCE, Cinnamon, MATE, LXQt and other environments.
CONTROL

mkdir -p "${OUT_DIR}"
dpkg-deb --root-owner-group --build "${STAGE}" "${DEB}" >/dev/null
echo "Built ${DEB}"
dpkg-deb --info "${DEB}" | sed -n '1,18p'
