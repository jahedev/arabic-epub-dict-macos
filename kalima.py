#!/usr/bin/env python3
"""
Kalima — Arabic EPUB reader for macOS.

This file is a thin entry-point that delegates everything to the
`kalima_app` package. Keep it small so PyInstaller has a stable anchor
and so anyone reading the source can find the real code next to it.

Run
---
    python kalima.py

Build
-----
    pyinstaller kalima.spec --noconfirm

The actual implementation lives in ``kalima_app/`` — see that package's
``__init__.py`` for the module map.
"""

from kalima_app.main import main


if __name__ == "__main__":
    raise SystemExit(main())
