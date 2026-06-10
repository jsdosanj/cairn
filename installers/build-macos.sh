#!/usr/bin/env bash
#
# Build the Cairn macOS distributables:
#   - a onefile binary (via PyInstaller + installers/cairn.spec)
#   - a flat .pkg installer (installs to /usr/local/bin and /usr/local/etc/cairn)
#   - a plain .tar.gz containing the binary + sample config
#
# Usage:
#   installers/build-macos.sh [VERSION]
#
set -euo pipefail

VERSION="${1:-1.0.0}"
IDENTIFIER="com.cairn.sync"

# Resolve repo root regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

SPEC="${SCRIPT_DIR}/cairn.spec"
DIST_DIR="${ROOT_DIR}/dist"
BUILD_DIR="${ROOT_DIR}/build"
OUT_DIR="${ROOT_DIR}/installers/output"
PKG_ROOT="${BUILD_DIR}/pkgroot"

BINARY="${DIST_DIR}/cairn"
CONFIG_SAMPLE="${ROOT_DIR}/config.example.yaml"

echo "==> Building Cairn ${VERSION} for macOS"

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
TARBALL="${OUT_DIR}/cairn-macos-${VERSION}.tar.gz"
TAR_STAGE="${BUILD_DIR}/tar-macos"
rm -rf "${TAR_STAGE}"
mkdir -p "${TAR_STAGE}"
cp "${BINARY}" "${TAR_STAGE}/cairn"
cp "${CONFIG_SAMPLE}" "${TAR_STAGE}/config.example.yaml"
tar -czf "${TARBALL}" -C "${TAR_STAGE}" .
echo "    wrote ${TARBALL}"

# ---------------------------------------------------------------------------
# .pkg
# ---------------------------------------------------------------------------
echo "==> Creating .pkg"
rm -rf "${PKG_ROOT}"
mkdir -p "${PKG_ROOT}/usr/local/bin"
mkdir -p "${PKG_ROOT}/usr/local/etc/cairn"
cp "${BINARY}" "${PKG_ROOT}/usr/local/bin/cairn"
chmod 755 "${PKG_ROOT}/usr/local/bin/cairn"
cp "${CONFIG_SAMPLE}" "${PKG_ROOT}/usr/local/etc/cairn/config.example.yaml"

PKG="${OUT_DIR}/cairn-macos-${VERSION}.pkg"
pkgbuild \
  --root "${PKG_ROOT}" \
  --identifier "${IDENTIFIER}" \
  --version "${VERSION}" \
  --install-location "/" \
  "${PKG}"
echo "    wrote ${PKG}"

echo "==> macOS build complete. Artifacts:"
echo "    ${PKG}"
echo "    ${TARBALL}"
