# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Cairn (formerly GhostAssetSync).

Builds the `ghostsync.py` entrypoint into a single-file console binary named
`cairn`.

The source/sink/notifier plugins are imported lazily via importlib in
src/cairn/registry.py, so PyInstaller's static analysis cannot discover them.
They are listed explicitly in ``hiddenimports`` below.

Build with:
    pyinstaller installers/cairn.spec
"""

import os

# The spec is invoked from the repo root (where pyinstaller is run), so derive
# paths relative to the current working directory rather than __file__, which
# PyInstaller does not define for spec files.
PROJECT_ROOT = os.path.abspath(os.getcwd())
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
ENTRYPOINT = os.path.join(PROJECT_ROOT, "ghostsync.py")

hiddenimports = [
    "cairn.sources.jamf",
    "cairn.sources.intune",
    "cairn.sources.jumpcloud",
    "cairn.sources.crowdstrike",
    "cairn.sources.sophos",
    "cairn.sources.defender",
    "cairn.sinks.snipeit",
    "cairn.notifiers.teams",
    "cairn.notifiers.slack",
    "cairn.notifiers.webhook",
]


block_cipher = None


a = Analysis(
    [ENTRYPOINT],
    pathex=[SRC_DIR],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="cairn",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
