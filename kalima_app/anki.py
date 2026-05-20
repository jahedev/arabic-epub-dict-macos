"""
anki — Export saved vocabulary to an Anki ``.apkg`` package.

Cards use a deterministic GUID derived from ``(book_id, normalized_word)``
so re-exporting the same word updates the existing Anki note rather than
creating a duplicate. Each book becomes its own subdeck under
``Kalima::<book title>``.

Requires the ``genanki`` package. If it isn't installed we raise at call
time so the rest of the app stays usable.
"""

from __future__ import annotations

import re
import zlib
from collections import defaultdict
from pathlib import Path

from .config import ANKI_MODEL_ID
from .models import SavedVocab


# genanki is optional. Importing here lets the app start even when it's
# missing — callers handle the resulting RuntimeError with a friendly UI.
try:
    import genanki as _genanki  # type: ignore
except ImportError:
    _genanki = None  # type: ignore[assignment]


def is_available() -> bool:
    """True if genanki is importable (used to gate UI affordances)."""
    return _genanki is not None


def _anki_model():
    """Define the Kalima Arabic card type used for every exported note."""
    assert _genanki is not None
    return _genanki.Model(
        ANKI_MODEL_ID,
        "Kalima Arabic",
        fields=[
            {"name": "Arabic"},
            {"name": "Definition"},
            {"name": "DictionaryDef"},
            {"name": "Note"},
            {"name": "Source"},
        ],
        templates=[{
            "name": "Recognition",
            "qfmt": '<div class="arabic">{{Arabic}}</div>',
            "afmt": (
                '{{FrontSide}}<hr id="answer">'
                '<div class="definition">{{Definition}}</div>'
                '{{#DictionaryDef}}<div class="dictdef">{{DictionaryDef}}</div>{{/DictionaryDef}}'
                '{{#Note}}<div class="note">{{Note}}</div>{{/Note}}'
                '<div class="source">{{Source}}</div>'
            ),
        }],
        css=(
            ".card{font-family:'Geeza Pro',serif;font-size:20px;text-align:center;}"
            ".arabic{font-size:36px;font-weight:bold;direction:rtl;margin:16px 0;}"
            ".definition{direction:rtl;font-size:18px;margin:12px 0;}"
            ".dictdef{color:#555;font-size:13px;border-top:1px solid #eee;"
            "padding-top:8px;margin-top:8px;direction:rtl;}"
            ".note{color:#7c5000;font-size:13px;font-style:italic;margin:8px 0;}"
            ".source{color:#aaa;font-size:11px;margin-top:16px;}"
        ),
    )


def build_anki_package(records: list[SavedVocab], output_path: Path) -> int:
    """Build an .apkg from ``records`` and write it to ``output_path``.

    Returns the number of cards written. Cards are grouped into ``Kalima::``
    subdecks by book title. The note GUIDs are derived from the book ID and
    normalized word so re-imports update existing cards in place.
    """
    if _genanki is None:
        raise RuntimeError("genanki is not installed. Run: pip install genanki")

    model = _anki_model()

    # Group records by book so each book becomes its own subdeck.
    by_book: dict[str, list[SavedVocab]] = defaultdict(list)
    for r in records:
        by_book[r.book_id].append(r)

    decks = []
    for book_id, book_records in by_book.items():
        book_title = book_records[0].book_title or book_id
        deck_name = f"Kalima::{book_title}"
        # zlib.crc32 is deterministic across runs (unlike hash()), so the
        # same deck name always maps to the same Anki deck.
        deck_id = zlib.crc32(deck_name.encode()) & 0x7FFFFFFF
        deck = _genanki.Deck(deck_id, deck_name)

        for r in book_records:
            source = r.book_title or ""
            if r.chapter_title:
                source += f" · {r.chapter_title}"

            # The Definition field is plain text — strip any leftover HTML
            # from legacy entries that were saved as full HTML strings.
            plain_def = re.sub(r"<[^>]+>", "", r.saved_definition).strip()

            note = _genanki.Note(
                model=model,
                fields=[
                    r.word,
                    plain_def,
                    r.dictionary_definition or "",
                    r.note or "",
                    source,
                ],
                guid=_genanki.guid_for(book_id, r.normalized_word),
            )
            deck.add_note(note)
        decks.append(deck)

    package = _genanki.Package(decks)
    package.write_to_file(str(output_path))
    return sum(len(d.notes) for d in decks)
