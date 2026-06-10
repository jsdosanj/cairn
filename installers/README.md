# Cairn installers

This directory contains everything needed to build the Cairn (formerly
GhostAssetSync) CLI into native installers for macOS, Linux, and Windows.

All builds compile `ghostsync.py` into a single-file binary named `cairn`
using PyInstaller and the shared spec [`cairn.spec`](./cairn.spec). The plugin
modules under `cairn.sources`, `cairn.sinks`, and `cairn.notifiers` are imported
lazily via `importlib`, so they are declared as `hiddenimports` in the spec.

## Prerequisites

- Python 3.11
- `pip install -r ../requirements.txt`
- `pip install pyinstaller`

## Building locally

The build scripts take an optional version argument (default `1.0.0`) and write
artifacts to `installers/output/`.

### macOS

```bash
installers/build-macos.sh 1.0.0
```

Produces:

- `cairn-macos-<version>.pkg` — installs the `cairn` binary to
  `/usr/local/bin` and `config.example.yaml` to `/usr/local/etc/cairn/`
  (identifier `com.cairn.sync`).
- `cairn-macos-<version>.tar.gz` — the binary plus sample config.

### Linux

```bash
installers/build-linux.sh 1.0.0
```

Produces:

- `cairn-linux-<version>.deb` — installs the `cairn` binary to
  `/usr/local/bin/cairn` and the sample config to
  `/etc/cairn/config.example.yaml`.
- `cairn-linux-<version>.tar.gz` — the binary plus sample config.

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File installers\build-windows.ps1 1.0.0
```

Produces:

- `cairn-windows-x64.zip` — `cairn.exe`, `config.example.yaml`, and
  `README-INSTALL.txt`.

To additionally build a full `.exe` installer, open
[`windows-setup.iss`](./windows-setup.iss) in Inno Setup (or run
`ISCC.exe windows-setup.iss`) after running the PowerShell build. The installer
places `cairn.exe` under `Program Files\Cairn` and optionally adds it to PATH.

## CI artifacts

The GitHub Actions workflow [`.github/workflows/release.yml`](../.github/workflows/release.yml)
runs on tag pushes matching `v*`. It builds on `macos-latest`,
`ubuntu-latest`, and `windows-latest`, then publishes a GitHub Release with:

- `cairn-macos-<version>.pkg`
- `cairn-macos-<version>.tar.gz`
- `cairn-linux-<version>.deb`
- `cairn-linux-<version>.tar.gz`
- `cairn-windows-x64.zip`
