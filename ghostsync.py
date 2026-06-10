#!/usr/bin/env python3
"""Cairn entrypoint (formerly GhostAssetSync).

Kept as `ghostsync.py` for back-compat with existing JAMF/GPO/Intune deployment
scripts. Delegates to the `cairn` package. Once installed via pip, prefer the
`cairn` console command.
"""

import os
import sys

# Allow running straight from a checkout without `pip install`.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from cairn.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
