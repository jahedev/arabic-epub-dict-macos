"""
models — Plain-data dataclasses used across the app.

These are deliberately small and dependency-free so any module can import
them without dragging in Qt, ebooklib, or genanki.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Chapter:
    """One entry from the EPUB spine, mapped to an extracted HTML file."""

    idref: str          # spine idref → matches an item id in the EPUB manifest
    title: str          # human-readable title (h1/h2/<title>, with fallback)
    item_name: str      # path inside the EPUB ZIP
    file_path: Path     # path to the extracted file in the temp dir


@dataclass
class SavedVocab:
    """A row from the `vocab` table — exactly what we display in the browser."""

    id: int
    book_id: str               # SHA-256 of the EPUB file
    normalized_word: str       # diacritic-stripped, alef-normalized form (the key)
    word: str                  # original surface form the user clicked
    dictionary_term: str       # whichever variant Dictionary.app actually matched
    saved_definition: str      # user-edited definition (plain text or legacy HTML)
    dictionary_definition: str # original DCSCopyTextDefinition output
    note: str                  # optional user note
    book_title: str
    chapter_title: str
    chapter_index: int
    saved_at: str              # ISO 8601, set on first save
    updated_at: str            # ISO 8601, refreshed on every save


@dataclass
class LookupRecord:
    """Everything we know about an in-progress word lookup.

    Built fresh on every click. Carries enough context for the popup,
    the save dialog, and the eventual DB write to share a single value.
    """

    clicked_word: str = ""
    normalized_word: str = ""
    term_used: str = ""                   # the variant that actually hit the dict
    dictionary_definition: str = ""
    book_id: str = ""
    book_title: str = ""
    chapter: str = ""
    chapter_index: int = -1
    saved: Optional[SavedVocab] = None    # existing DB row, if any
    displayed_definition: str = ""        # which body of text the popup is showing
    displayed_source: str = "Dictionary"  # "Dictionary" or "Saved definition"
