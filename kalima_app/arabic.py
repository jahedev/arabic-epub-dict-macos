"""
arabic — Word normalization, macOS Dictionary lookup, and lookup-popup HTML.

This module is split into three logical sections:

1. **Normalization** — cleaning whitespace/punctuation, stripping diacritics,
   and generating lookup variants we'll try against the system dictionary.

2. **Dictionary lookup** — talking to Apple's Dictionary Services
   (DCSCopyTextDefinition). Returns plain text on success or a friendly
   error string when running outside macOS / without PyObjC.

3. **Formatting** — turning the plain-text dictionary result into the
   rich HTML shown in the in-app popup, plus utilities for converting
   between user-editable plain text and the popup's HTML representation.
"""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from .config import ARABIC_DIACRITICS_RE, TRIM_CHARS

if TYPE_CHECKING:
    from .models import LookupRecord


# DictionaryServices is only available on macOS via PyObjC. Import lazily and
# fall back to None so the app still loads on other platforms or in test runs.
try:
    from DictionaryServices import DCSCopyTextDefinition  # type: ignore
except Exception:  # noqa: BLE001 — PyObjC raises a custom ImportError variant
    DCSCopyTextDefinition = None  # type: ignore[assignment]


# ── Normalization ─────────────────────────────────────────────────────────────

def clean_lookup_word(word: str) -> str:
    """Trim punctuation/whitespace/bidi marks and collapse internal whitespace."""
    word = (word or "").strip(TRIM_CHARS)
    word = word.replace("ـ", "")  # tatweel (kashida) — never semantic
    word = re.sub(r"\s+", " ", word)
    return word.strip(TRIM_CHARS)


def normalize_arabic(word: str) -> str:
    """Aggressive normalization for use as the DB key.

    Strips diacritics and tatweel, then unifies the various alef and ya
    glyphs that learners often type interchangeably. Two surface forms
    that differ only in diacritics or alef shape collapse to the same key.
    """
    word = clean_lookup_word(word)
    word = ARABIC_DIACRITICS_RE.sub("", word)
    word = word.replace("ـ", "")
    word = (
        word.replace("ٱ", "ا")  # ٱ → ا
            .replace("آ", "ا")  # آ → ا
            .replace("أ", "ا")  # أ → ا
            .replace("إ", "ا")  # إ → ا
    )
    word = word.replace("ى", "ي")  # ى → ي
    return word


def lookup_variants(word: str) -> list[str]:
    """Return a small list of variants to try against Dictionary.app, in order.

    Dictionary.app is often lemma-sensitive — sometimes the surface form
    works, sometimes only the diacritic-stripped or alef-normalized form
    does. We try each in turn and stop at the first hit.
    """
    word = clean_lookup_word(word)
    no_diacritics = ARABIC_DIACRITICS_RE.sub("", word)
    normalized_alef = (
        no_diacritics
        .replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ٱ", "ا")
    )

    variants: list[str] = []
    for candidate in (word, no_diacritics, normalized_alef):
        candidate = clean_lookup_word(candidate)
        if candidate and candidate not in variants:
            variants.append(candidate)
    return variants


# ── macOS Dictionary lookup ───────────────────────────────────────────────────

def dictionary_lookup(word: str) -> tuple[str, str]:
    """Look up ``word`` via macOS Dictionary Services.

    Returns ``(term_used, definition)`` — the term that actually produced
    the hit (one of the variants tried) and the plain-text definition.
    Returns a friendly error message when DictionaryServices is missing.
    """
    if DCSCopyTextDefinition is None:
        return word, (
            "Dictionary Services is unavailable.\n\n"
            "This app must run on macOS with:\n"
            "pip install pyobjc-framework-DictionaryServices"
        )

    for term in lookup_variants(word):
        try:
            result = DCSCopyTextDefinition(None, term, (0, len(term)))
        except Exception as exc:  # noqa: BLE001 — surface the raw PyObjC error
            return term, f"Dictionary lookup failed:\n{exc}"
        if result:
            return term, str(result)

    return word, "No definition found in the active macOS dictionaries."


# ── Formatting: plain dictionary text ↔ readable HTML ─────────────────────────

# Parts-of-speech we treat as their own block when reflowing the raw dict text.
_POS_TOKENS = (
    "noun", "verb", "adjective", "adverb", "plural",
    "preposition", "conjunction", "interjection",
)


def dictionary_definition_parts(definition: str) -> list[str]:
    """Reflow Apple's one-line dictionary result into separate display lines.

    Apple Dictionary Services returns one big string. We insert line breaks
    before the ▸ subentry marker, around numbered senses (1, 2, ...), and
    around part-of-speech labels. The result is a list of trimmed lines
    ready for either the read-only popup or the editable save dialog.
    """
    raw = (definition or "").strip()
    if not raw:
        raw = "No definition available."

    nl = chr(10)
    text = " ".join(raw.split())
    text = text.replace("▸", nl + "▸ ")

    # Break out numbered senses: " 1 " → "\n1 "
    for number in range(1, 30):
        text = text.replace(" " + str(number) + " ", nl + str(number) + " ")

    # Break out parts of speech: " noun " → "\nnoun "
    for pos in _POS_TOKENS:
        text = text.replace(" " + pos + " ", nl + pos + " ")

    parts = [line.strip() for line in text.split(nl) if line.strip()]
    return parts or [text]


def definition_text_to_editable_text(definition: str) -> str:
    """Plain-text version suited for the save dialog's QTextEdit."""
    return "\n".join(dictionary_definition_parts(definition))


def definition_text_to_readable_html(definition: str) -> str:
    """Format a dictionary result for the read-only popup as HTML divs."""
    parts = dictionary_definition_parts(definition)

    html_lines: list[str] = []
    for i, line in enumerate(parts):
        escaped = html.escape(line)
        if i == 0:
            escaped = escaped.replace(" | ", " <span class='bar'>|</span> ")
            html_lines.append("<div class='entry-head'>" + escaped + "</div>")
        elif line.lstrip().startswith("▸"):
            html_lines.append("<div class='subentry'>" + escaped + "</div>")
        elif line.strip() and line.strip()[0].isdigit():
            html_lines.append("<div class='sense'>" + escaped + "</div>")
        elif line.lower().split(" ", 1)[0] in _POS_TOKENS:
            html_lines.append("<div class='pos'>" + escaped + "</div>")
        else:
            html_lines.append("<div>" + escaped + "</div>")
    return "".join(html_lines)


def looks_like_html(text: str) -> bool:
    """Heuristic for old saved entries that were stored as full HTML strings."""
    sample = (text or "").strip().lower()
    return (
        sample.startswith("<html")
        or sample.startswith("<!doctype")
        or "<body" in sample
        or "<div" in sample
        or "<p" in sample
    )


def plain_text_to_user_html(text: str) -> str:
    """Wrap each line of plain text in a `<div>` for display in the popup."""
    lines = (text or "").splitlines() or [text or ""]
    return "".join("<div>" + html.escape(line) + "</div>" for line in lines)


def saved_definition_to_plain_text(text: str) -> str:
    """Convert a stored definition back to clean editable plain text.

    Handles three cases:
    * Newer entries: already plain text with newlines → returned as-is.
    * Legacy entries: full HTML strings → parsed and flattened.
    * Single-line dictionary dumps with ▸ → re-flowed.
    """
    text = text or ""
    if looks_like_html(text):
        soup = BeautifulSoup(text, "html.parser")
        text = soup.get_text("\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)
    if "\n" not in text and "▸" in text:
        return definition_text_to_editable_text(text)
    return text.strip()


def saved_definition_to_html(text: str) -> str:
    """Render a stored definition as the popup's HTML representation."""
    return plain_text_to_user_html(saved_definition_to_plain_text(text))


# ── Full popup HTML ───────────────────────────────────────────────────────────

# Kept as a module constant so the f-string above stays readable.
_POPUP_STYLE = """
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Geeza Pro', 'Arial', sans-serif;
    font-size: 17px;
    line-height: 1.38;
    margin: 0;
    padding: 0;
    color: #111;
    background: #fff;
}
.section {
    border-bottom: 1px solid #ddd;
    padding-bottom: 7px;
    margin-bottom: 8px;
}
.label {
    font-weight: 700;
    color: #555;
    margin-bottom: 3px;
    direction: ltr;
}
.word {
    font-size: 23px;
    font-weight: 800;
    direction: rtl;
    unicode-bidi: plaintext;
}
.meta {
    color: #666;
    margin-top: 2px;
}
.saved {
    color: #0b63ce;
    font-weight: 800;
}
.unsaved {
    color: #777;
    font-weight: 700;
}
.note {
    direction: rtl;
    unicode-bidi: plaintext;
    background: #f3f8ff;
    border: 1px solid #bcd7ff;
    border-radius: 8px;
    padding: 8px;
    white-space: pre-wrap;
}
.entry-head {
    font-size: 21px;
    font-weight: 700;
    margin-bottom: 7px;
    direction: rtl;
    unicode-bidi: plaintext;
}
.pos {
    font-weight: 700;
    color: #444;
    margin-top: 6px;
    margin-bottom: 2px;
    direction: ltr;
    unicode-bidi: plaintext;
}
.sense {
    margin-top: 6px;
    margin-bottom: 2px;
    font-weight: 600;
    direction: rtl;
    unicode-bidi: plaintext;
}
.subentry {
    margin-right: 18px;
    margin-top: 2px;
    direction: rtl;
    unicode-bidi: plaintext;
}
.bar { color: #777; }
div {
    white-space: normal;
    overflow-wrap: anywhere;
}
"""


def format_lookup_html(record: "LookupRecord") -> str:
    """Render the lookup popup body as a full self-contained HTML page."""
    word = html.escape(record.clicked_word)
    term = html.escape(record.term_used or record.clicked_word)
    book_title = html.escape(record.book_title or "")
    chapter = html.escape(record.chapter or "")
    source = html.escape(record.displayed_source)
    note = html.escape(record.saved.note if record.saved else "")
    saved_status = "Saved word" if record.saved else "Not saved yet"
    saved_status_class = "saved" if record.saved else "unsaved"

    if record.displayed_source == "Saved definition":
        definition_body = saved_definition_to_html(record.displayed_definition)
    else:
        definition_body = definition_text_to_readable_html(record.displayed_definition)

    note_block = ""
    if record.saved and note:
        note_block = (
            '<div class="section">'
            '<div class="label">Saved note</div>'
            f'<div class="note">{note}</div>'
            "</div>"
        )

    # The trailing <!-- ... --> block keeps the metadata around for future use
    # but hides it from the popup — matches the original behavior.
    return f"""
    <html>
    <head>
    <style>{_POPUP_STYLE}</style>
    </head>
    <body>
        <div class="section">
            <div class="label">Showing: {source}</div>
            {definition_body}
        </div>
        {note_block}
        <!--
        <div class="section">
            <div class="label">Word</div>
            <div class="word">{word}</div>
            <div class="meta">Dictionary term: {term}</div>
            <div class="meta {saved_status_class}">{saved_status}</div>
            <div class="meta">Book: {book_title}</div>
            <div class="meta">Chapter: {chapter}</div>
        </div>
        -->
    </body>
    </html>
    """
