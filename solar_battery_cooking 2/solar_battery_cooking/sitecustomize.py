"""Project-local Python startup customizations.

Ensures packages installed into `./.vendor` are importable without modifying
the user's global Python environment.
"""

from __future__ import annotations

import sys
from pathlib import Path


_VENDOR = Path(__file__).resolve().parent / ".vendor"
if _VENDOR.exists():
    vendor_str = str(_VENDOR)
    if vendor_str not in sys.path:
        sys.path.insert(0, vendor_str)
