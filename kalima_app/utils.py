"""
utils — Small dependency-free helpers shared across modules.

Limit this module to functions that don't need Qt, ebooklib, or sqlite3 —
those belong in their own focused modules.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from pathlib import Path


def app_now() -> str:
    """ISO 8601 timestamp, seconds precision. Used for DB created/updated columns."""
    return dt.datetime.now().isoformat(timespec="seconds")


def calculate_file_hash(path: Path) -> str:
    """SHA-256 of a file's contents.

    Used as the stable `book_id` so the same EPUB always maps to the same
    vocabulary regardless of where the user moves the file.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_output_path(base_dir: Path, item_name: str) -> Path:
    """Resolve ``item_name`` underneath ``base_dir``, refusing path traversal.

    EPUB archives are user-supplied. A malicious or sloppy zip could contain
    entries like ``../../etc/passwd``; this helper sanitizes the name so the
    resolved path always lives inside ``base_dir``. Falls back to a safe
    filename in ``base_dir`` itself if traversal is detected.
    """
    clean_name = item_name.replace("\\", "/").lstrip("/")
    target = (base_dir / clean_name).resolve()
    base = base_dir.resolve()
    if base != target and base not in target.parents:
        fallback = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(item_name).name or "epub_item")
        target = base / fallback
    return target
