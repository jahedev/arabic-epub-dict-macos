"""
epub_book — Extract EPUB contents to a temp dir and walk the spine.

`EpubBook` is a thin wrapper around `ebooklib`:

1. **Open**: extract every manifest item into a temp directory (so chapter
   HTML can reference local images/CSS via file://), and prepare an
   ordered list of `Chapter` objects from the spine.

2. **Robustness**: ebooklib eagerly reads every manifest item when loading,
   with no error handling — a long-standing bug (issues #161, #197, #222,
   #281). EPUBs that list resources missing from the ZIP raise KeyError
   and abort the entire load. We monkey-patch `EpubReader.read_file` at
   import time so missing files yield empty bytes instead of crashing.

3. **HTML prep**: every chapter's HTML gets `<meta charset>` plus the
   reader stylesheet injected into `<head>` before being written to disk.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from .config import READER_CSS
from .models import Chapter
from .utils import calculate_file_hash, safe_output_path


# ── ebooklib safety patch (must run at import time) ──────────────────────────
# Wrap EpubReader.read_file so missing manifest entries return b"" instead
# of raising KeyError. The patch is applied once when this module loads.
_orig_epub_read_file = epub.EpubReader.read_file


def _safe_epub_read_file(self, name: str) -> bytes:  # noqa: ANN001 — ebooklib signature
    try:
        return _orig_epub_read_file(self, name)
    except KeyError:
        print(f"Warning: missing EPUB resource skipped during load: {name}")
        return b""


epub.EpubReader.read_file = _safe_epub_read_file  # type: ignore[assignment]


def get_epub_item_content_safe(item) -> Optional[bytes]:  # noqa: ANN001 — ebooklib item
    """Return ``item.get_content()`` or None if the resource is broken.

    Some EPUBs list files in the manifest that are missing from the ZIP
    (typical example: a missing font referenced by stylesheet). Skipping
    them keeps the reader functional instead of aborting.
    """
    try:
        return item.get_content()
    except KeyError as exc:
        print(f"Warning: missing EPUB resource skipped: {item.get_name()} ({exc})")
        return None
    except Exception as exc:  # noqa: BLE001 — surface unexpected issues but keep loading
        print(f"Warning: could not read EPUB resource skipped: {item.get_name()} ({exc})")
        return None


class EpubBook:
    """Mutable container for a single opened EPUB.

    Reopening calls `close()` first, so a single instance can be reused
    across multiple "Open EPUB" actions in the same session.
    """

    def __init__(self) -> None:
        self.path: Optional[Path] = None
        self.tempdir: Optional[tempfile.TemporaryDirectory[str]] = None
        self.chapters: list[Chapter] = []
        self.book_id: str = ""
        self.title: str = ""

    def close(self) -> None:
        """Drop chapter list and clean up the extraction tempdir."""
        self.chapters = []
        self.path = None
        self.book_id = ""
        self.title = ""
        if self.tempdir is not None:
            self.tempdir.cleanup()
            self.tempdir = None

    def open(self, epub_path: str | os.PathLike[str]) -> None:
        """Load an EPUB from disk, extract assets, and build the chapter list."""
        self.close()
        self.path = Path(epub_path)
        self.book_id = calculate_file_hash(self.path)
        self.tempdir = tempfile.TemporaryDirectory(prefix="kalima_epub_")
        out_dir = Path(self.tempdir.name)

        book = epub.read_epub(str(self.path))
        self.title = self._extract_book_title(book) or self.path.stem

        # Extract every EPUB item so chapter HTML can load images/CSS/fonts.
        for item in book.get_items():
            name = item.get_name() or f"item_{id(item)}"
            content = get_epub_item_content_safe(item)
            if content is None:
                continue  # broken/missing resource — skip silently

            target = safe_output_path(out_dir, name)
            target.parent.mkdir(parents=True, exist_ok=True)

            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                content = self._prepare_html(content)

            target.write_bytes(content)

        # Build chapter list, preferring the spine for ordering.
        document_items_by_id = {
            item.get_id(): item
            for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_DOCUMENT
        }

        chapters: list[Chapter] = []
        for spine_entry in book.spine:
            idref = spine_entry[0] if isinstance(spine_entry, (tuple, list)) else spine_entry
            item = document_items_by_id.get(idref)
            if not item:
                continue
            content = get_epub_item_content_safe(item)
            if content is None:
                continue
            title = self._extract_title(content, item.get_name())
            chapters.append(
                Chapter(
                    idref=idref,
                    title=title,
                    item_name=item.get_name(),
                    file_path=safe_output_path(out_dir, item.get_name()),
                )
            )

        # Fallback for malformed EPUBs without a useful spine.
        if not chapters:
            for item in document_items_by_id.values():
                content = get_epub_item_content_safe(item)
                if content is None:
                    continue
                title = self._extract_title(content, item.get_name())
                chapters.append(
                    Chapter(
                        idref=item.get_id(),
                        title=title,
                        item_name=item.get_name(),
                        file_path=safe_output_path(out_dir, item.get_name()),
                    )
                )

        if not chapters:
            raise ValueError("No readable HTML/XHTML chapters were found in this EPUB.")

        self.chapters = chapters

    # ── Internals ────────────────────────────────────────────────────────────

    def _prepare_html(self, content: bytes) -> bytes:
        """Inject our `<style>` + meta charset into a chapter's HTML.

        Tries XML parsing first because EPUB documents are XHTML; falls
        back to HTML parsing for malformed files.
        """
        try:
            soup = BeautifulSoup(content, "lxml-xml")
        except Exception:  # noqa: BLE001
            soup = BeautifulSoup(content, "html.parser")

        # Some chapters are bare fragments — wrap them in a real document.
        if soup.html is None:
            html_tag = soup.new_tag("html")
            body_tag = soup.new_tag("body")
            body_tag.append(soup)
            html_tag.append(body_tag)
            soup = BeautifulSoup(str(html_tag), "html.parser")

        if soup.head is None:
            head = soup.new_tag("head")
            soup.html.insert(0, head)

        meta = soup.new_tag("meta")
        meta.attrs["charset"] = "utf-8"
        soup.head.insert(0, meta)

        style = soup.new_tag("style")
        style.attrs["id"] = "arabic-reader-style"
        style.string = READER_CSS
        soup.head.append(style)

        if soup.body is not None:
            existing_class = soup.body.get("class", [])
            if isinstance(existing_class, str):
                existing_class = [existing_class]
            soup.body["class"] = existing_class + ["arabic-reader-body"]
            soup.body["dir"] = "rtl"

        return str(soup).encode("utf-8")

    def _extract_book_title(self, book: epub.EpubBook) -> str:
        """Pull the DC:title from the OPF metadata, if present."""
        try:
            titles = book.get_metadata("DC", "title")
        except Exception:  # noqa: BLE001
            titles = []
        for title_item in titles:
            if title_item and title_item[0]:
                return str(title_item[0]).strip()
        return ""

    def _extract_title(self, content: bytes, fallback: str) -> str:
        """Best-effort chapter title from h1 → h2 → <title> → filename stem."""
        try:
            soup = BeautifulSoup(content, "lxml-xml")
        except Exception:  # noqa: BLE001
            soup = BeautifulSoup(content, "html.parser")

        for selector in ("h1", "h2", "title"):
            tag = soup.find(selector)
            if tag:
                text = " ".join(tag.get_text(" ", strip=True).split())
                if text:
                    return text[:80]
        return Path(fallback).stem.replace("_", " ")[:80] or "Chapter"
