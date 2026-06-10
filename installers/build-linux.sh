#!/usr/bin/env bash
#
# Build the Cairn Linux distributables:
#   - a onefile binary (via PyInstaller + installers/cairn.spec)
#   - a plain .tar.gz containing the binary + sample config
#   - a .deb package (binary -> /usr/local/bin, sample config -> /etc/cairn)
#
# Usage:
#   installers/build-linux.sh [VERSION]
#
set -euo pipefail

VERSION="${1:-1.0.0}"

# Resolve repo root regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

SPEC="${SCRIPT_DIR}/cairn.spec"
DIST_DIR="${ROOT_DIR}/dist"
BUILD_DIR="${ROOT_DIR}/build"
OUT_DIR="${ROOT_DIR}/installers/output"

BINARY="${DIST_DIR}/cairn"
CONFIG_SAMPLE="${ROOT_DIR}/config.example.yaml"

echo "==> Building Cairn ${VERSION} for Linux"

mkdir -p "${OUT_DIR}"

echo "==> Running PyInstaller"
cd "${ROOT_DIR}"
pyinstaller --noconfirm --clean --distpath "${DIST_DIR}" --workpath "${BUILD_DIR}" "${SPEC}"

if [[ ! -f "${BINARY}" ]]; then
  echo "ERROR: expected binary not found at ${BINARY}" >&2
  exit 1
fi
chmod +x "${BINARY}"

# ---------------------------------------------------------------------------
# tar.gz
# ---------------------------------------------------------------------------
echo "==> Creating tar.gz"
TARBALL="${OUT_DIR}/cairn-linux-${VERSION}.tar.gz"
TAR_STAGE="${BUILD_DIR}/tar-linux"
rm -rf "${TAR_STAGE}"
mkdir -p "${TAR_STAGE}"
cp "${BINARY}" "${TAR_STAGE}/cairn"
cp "${CONFIG_SAMPLE}" "${TAR_STAGE}/config.example.yaml"
tar -czf "${TARBALL}" -C "${TAR_STAGE}" .
echo "    wrote ${TARBALL}"

# ---------------------------------------------------------------------------
# .deb
# ---------------------------------------------------------------------------
echo "==> Creating .deb"
DEB_ROOT="${BUILD_DIR}/debroot"
rm -rf "${DEB_ROOT}"
mkdir -p "${DEB_ROOT}/DEBIAN"
mkdir -p "${DEB_ROOT}/usr/local/bin"
mkdir -p "${DEB_ROOT}/etc/cairn"

cp "${BINARY}" "${DEB_ROOT}/usr/local/bin/cairn"
chmod 755 "${DEB_ROOT}/usr/local/bin/cairn"
cp "${CONFIG_SAMPLE}" "${DEB_ROOT}/etc/cairn/config.example.yaml"

cat > "${DEB_ROOT}/DEBIAN/control" <<EOF
Package: cairn
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: amd64
Maintainer: Cairn contributors <noreply@example.com>
Description: Reconcile device inventory from MDM/EDR tools into Snipe-IT.
 Cairn (formerly GhostAssetSync) is a pluggable sync engine that reconciles
 device inventory from MDM/EDR tools (Jamf, Intune, JumpCloud, CrowdStrike,
 Sophos, Microsoft Defender) into an asset system of record (Snipe-IT),
 with chat/webhook notifications.
EOF

DEB="${OUT_DIR}/cairn-linux-${VERSION}.deb"
dpkg-deb --build --root-owner-group "${DEB_ROOT}" "${DEB}"
echo "    wrote ${DEB}"

echo "==> Linux build complete. Artifacts:"
echo "    ${DEB}"
echo "    ${TARBALL}"
