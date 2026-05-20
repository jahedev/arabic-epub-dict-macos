#!/usr/bin/env python3
"""
Arabic EPUB Reader with macOS Dictionary.app popup lookup

Features
- Open and read EPUB files
- Chapter/sidebar navigation
- RTL-friendly Arabic display
- Font zoom controls
- Find-in-chapter search
- Click any word to show the macOS Dictionary Services result
- Optional macOS Dictionary.app lookup mode through dict://word
- Save vocabulary to a local SQLite database
- Edit the saved definition and note before saving
- Blue-highlight saved words when reopening the same EPUB
- Toggle between showing Dictionary definition and your saved definition
- Export saved vocabulary to CSV for review or Anki import

macOS setup
    python3 -m venv epubdict-env
    source epubdict-env/bin/activate
    pip install PyQt6 PyQt6-WebEngine ebooklib beautifulsoup4 lxml pyobjc-framework-DictionaryServices

Run
    python arabic_epub_dictionary_reader.py

Before running, open Dictionary.app > Settings/Preferences and enable Oxford Arabic Dictionary.
Put the Oxford Arabic dictionary higher in the list if you want it to be preferred.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import subprocess
import tempfile
import urllib.request as _urllib_req
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

try:
    import ebooklib
    from ebooklib import epub
except ImportError as exc:
    raise SystemExit(
        "Missing EPUB dependencies. Install with:\n"
        "pip install ebooklib beautifulsoup4 lxml"
    ) from exc
else:
    # ebooklib eagerly reads every manifest item in read_epub() with no error
    # handling — a long-standing unfixed bug (issues #161, #197, #222, #281).
    # EPUBs that list fonts or images in the manifest but omit them from the
    # ZIP raise KeyError and abort the entire load.  Patching read_file() once
    # here makes those missing entries return empty bytes instead of crashing.
    _orig_epub_read_file = epub.EpubReader.read_file

    def _safe_epub_read_file(self, name: str) -> bytes:
        try:
            return _orig_epub_read_file(self, name)
        except KeyError:
            print(f"Warning: missing EPUB resource skipped during load: {name}")
            return b""

    epub.EpubReader.read_file = _safe_epub_read_file

try:
    from bs4 import BeautifulSoup
except ImportError as exc:
    raise SystemExit("Missing beautifulsoup4. Install with: pip install beautifulsoup4 lxml") from exc

try:
    from DictionaryServices import DCSCopyTextDefinition
except Exception:  # macOS/PyObjC only
    DCSCopyTextDefinition = None

try:
    import genanki as _genanki
except ImportError:
    _genanki = None  # type: ignore[assignment]

try:
    from PyQt6.QtCore import Qt, QByteArray, QSize, QUrl, QSettings, QThread, QTimer, pyqtSignal
    from PyQt6.QtGui import (
        QAction, QActionGroup, QCursor, QDesktopServices, QGuiApplication, QIcon,
        QKeySequence, QPainter, QPalette, QPixmap,
    )
    from PyQt6.QtSvg import QSvgRenderer
    from PyQt6.QtWidgets import (
        QApplication,
        QFileDialog,
        QInputDialog,
        QDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QMainWindow,
        QMenu,
        QMessageBox,
        QPushButton,
        QComboBox,
        QSizePolicy,
        QSplitter,
        QStatusBar,
        QTextEdit,
        QToolBar,
        QVBoxLayout,
        QWidget,
    )
    from PyQt6.QtWebEngineCore import QWebEnginePage
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError as exc:
    raise SystemExit(
        "Missing PyQt6 dependencies. Install with:\n"
        "pip install PyQt6 PyQt6-WebEngine"
    ) from exc


APP_ORG = "Kalima"
APP_NAME = "Kalima"

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
VOCAB_DB_PATH = APP_SUPPORT_DIR / "vocabulary.sqlite3"
VOCAB_CSV_PATH = Path.home() / "Documents" / "kalima_vocab.csv"

# Asset paths — work both from source and inside a PyInstaller bundle
if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    _BASE_DIR = Path(__file__).parent

ICONS_DIR = _BASE_DIR / "assets" / "icons"


def svg_icon(name: str, color: str | None = None, size: int = 20) -> "QIcon":
    """Load an SVG from assets/icons/, substitute currentColor, return a QIcon.

    When *color* is None (default) the color is chosen automatically:
    light gray on a dark toolbar, dark gray on a light toolbar, so icons
    stay legible regardless of the macOS appearance setting.
    """
    if color is None:
        app = QApplication.instance()
        if app is not None:
            bg = app.palette().color(QPalette.ColorRole.Window)
            color = "#ececec" if bg.lightness() < 128 else "#3a3a3c"
        else:
            color = "#3a3a3c"
    path = ICONS_DIR / f"{name}.svg"
    if not path.exists():
        return QIcon()
    svg_bytes = path.read_bytes().replace(b"currentColor", color.encode())
    renderer = QSvgRenderer(QByteArray(svg_bytes))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)

ARABIC_DIACRITICS_RE = re.compile(
    r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]"
)

TRIM_CHARS = """\ufeff\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069
\t\r\n .,;:!?()[]{}<>\"'“”‘’،؛؟«»…ـ"""

READER_CSS = """
html, body {
    direction: rtl;
    text-align: right;
    font-family: -apple-system, BlinkMacSystemFont, "Geeza Pro", "Arial", "Times New Roman", serif;
    font-size: 21px;
    line-height: 1.9;
    margin: 0;
    padding: 24px 38px;
    background: #fffdf8;
    color: #1f1f1f;
}
p, div, li, blockquote {
    line-height: 1.9;
}
a {
    color: inherit;
    text-decoration: underline;
}
img, svg, video {
    max-width: 100%;
    height: auto;
}
.lookup-word {
    cursor: pointer;
    border-radius: 4px;
}
.lookup-word:hover {
    background: rgba(255, 220, 120, 0.55);
}
.lookup-word-active {
    background: rgba(255, 210, 80, 0.75) !important;
}
.lookup-word-saved {
    background: rgba(80, 155, 255, 0.24);
}
.lookup-word-saved:hover {
    background: rgba(80, 155, 255, 0.38);
}
::selection {
    background: #ffe8a3;
    color: #1a1a1a;
}
html.reader-dark ::selection {
    background: #4a6fa5;
    color: #ffffff;
}
html.reader-dark, html.reader-dark body {
    background: #1c1c1e !important;
    color: #e5e5e5 !important;
}
html.reader-dark .lookup-word:hover {
    background: rgba(255, 210, 80, 0.3) !important;
}
html.reader-dark .lookup-word-saved {
    background: rgba(80, 155, 255, 0.18) !important;
}
html.reader-dark a {
    color: #a8c8ff !important;
}
@media (max-width: 540px) {
    html, body { padding: 16px 20px; }
}
@media (max-width: 380px) {
    html, body { padding: 12px 12px; }
}
"""

WORD_AT_POINT_JS = r"""
(function() {
    const x = __X__;
    const y = __Y__;

    function clean(s) {
        if (!s) return "";
        return s
            .replace(/[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g, "")
            .replace(/^[\s.,;:!?()\[\]{}<>"'“”‘’،؛؟«»…ـ]+/g, "")
            .replace(/[\s.,;:!?()\[\]{}<>"'“”‘’،؛؟«»…ـ]+$/g, "")
            .replace(/\s+/g, " ")
            .trim();
    }

    const selection = window.getSelection ? window.getSelection().toString().trim() : "";
    if (selection && selection.length <= 80) {
        return {word: clean(selection.split(/\s+/)[0])};
    }

    const el = document.elementFromPoint(x, y);
    if (el && el.closest) {
        const span = el.closest(".lookup-word");
        if (span && span.dataset && span.dataset.word) {
            return {word: clean(span.dataset.word)};
        }
    }

    return {word: ""};
})();
"""

INSTALL_WORD_LOOKUP_JS = r"""
(function() {
    if (window.__arabicReaderLookupInstalled) return "already-installed";
    window.__arabicReaderLookupInstalled = true;

    const wordRe = /([\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFFA-Za-zÀ-ÖØ-öø-ÿ0-9’'\-]+)/g;
    const skipTags = new Set(["SCRIPT", "STYLE", "TEXTAREA", "INPUT", "SELECT", "OPTION", "CODE", "PRE"]);

    function clean(s) {
        if (!s) return "";
        return s
            .replace(/[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g, "")
            .replace(/^[\s.,;:!?()\[\]{}<>"'“”‘’،؛؟«»…ـ]+/g, "")
            .replace(/[\s.,;:!?()\[\]{}<>"'“”‘’،؛؟«»…ـ]+$/g, "")
            .replace(/\s+/g, " ")
            .trim();
    }

    function normalizeArabic(s) {
        return clean(s)
            .replace(/[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]/g, "")
            .replace(/ـ/g, "")
            .replace(/[ٱآأإ]/g, "ا")
            .replace(/ى/g, "ي");
    }

    window.__arabicReaderNormalize = normalizeArabic;

    function markIfSaved(span) {
        const norm = normalizeArabic(span.dataset.word || span.textContent || "");
        span.dataset.norm = norm;
        if (window.__arabicReaderSavedWords && window.__arabicReaderSavedWords.has(norm)) {
            span.classList.add("lookup-word-saved");
        } else {
            span.classList.remove("lookup-word-saved");
        }
    }

    function shouldSkip(node) {
        const parent = node.parentNode;
        if (!parent) return true;
        if (parent.classList && parent.classList.contains("lookup-word")) return true;
        if (skipTags.has(parent.nodeName)) return true;
        return false;
    }

    function wrapTextNode(textNode) {
        if (shouldSkip(textNode)) return;
        const text = textNode.nodeValue;
        if (!text || !wordRe.test(text)) return;
        wordRe.lastIndex = 0;

        const frag = document.createDocumentFragment();
        let lastIndex = 0;
        let match;
        while ((match = wordRe.exec(text)) !== null) {
            const raw = match[0];
            const start = match.index;
            if (start > lastIndex) {
                frag.appendChild(document.createTextNode(text.slice(lastIndex, start)));
            }
            const span = document.createElement("span");
            span.className = "lookup-word";
            span.dataset.word = clean(raw);
            span.textContent = raw;
            markIfSaved(span);
            frag.appendChild(span);
            lastIndex = start + raw.length;
        }
        if (lastIndex < text.length) {
            frag.appendChild(document.createTextNode(text.slice(lastIndex)));
        }
        textNode.parentNode.replaceChild(frag, textNode);
    }

    const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(wrapTextNode);

    document.addEventListener("click", function(e) {
        const el = e.target && e.target.closest ? e.target.closest(".lookup-word") : null;
        if (!el) return;
        const word = clean(el.dataset.word || el.textContent || "");
        if (!word) return;

        document.querySelectorAll(".lookup-word-active").forEach(function(x) {
            x.classList.remove("lookup-word-active");
        });
        el.classList.add("lookup-word-active");

        e.preventDefault();
        e.stopPropagation();
        window.location.href = "lookup://word?value=" + encodeURIComponent(word);
    }, true);

    return "installed";
})();
"""

TOGGLE_TASHKEEL_JS = r"""
(function(hidden) {
    function stripTashkeel(s) {
        return (s || "")
            .replace(/[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]/g, "");
    }

    document.querySelectorAll(".lookup-word").forEach(function(el) {
        if (!el.dataset.originalText) {
            el.dataset.originalText = el.textContent || "";
        }

        if (hidden) {
            el.textContent = stripTashkeel(el.dataset.originalText);
        } else {
            el.textContent = el.dataset.originalText;
        }
    });

    document.body.classList.toggle("hide-tashkeel", hidden);
})(__HIDDEN__);
"""

APPLY_DARK_MODE_JS = r"""
(function(dark) {
    document.documentElement.classList.toggle('reader-dark', dark);
})(__DARK__);
"""

MAX_RECENT_FILES = 10

_FONT_WEIGHT_RE = re.compile(
    r"-(Regular|Bold|Italic|Light|Medium|SemiBold|ExtraBold|Black|Thin|Variable).*$",
    re.IGNORECASE,
)


@dataclass
class FontOption:
    display_name: str       # shown in the picker, e.g. "Amiri"
    css_family: str         # value used in CSS font-family
    file_path: Optional[Path]  # .ttf path, or None for system default


def camel_to_spaces(s: str) -> str:
    """Convert CamelCase to space-separated words, keeping acronyms together."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", s)
    return s.strip()


def load_font_options() -> list[FontOption]:
    """Return all available reader fonts: system default first, then bundled .ttf files."""
    options: list[FontOption] = [
        FontOption(
            display_name="System Default",
            css_family="-apple-system, BlinkMacSystemFont, 'Geeza Pro', Arial, serif",
            file_path=None,
        )
    ]
    fonts_dir = _BASE_DIR / "assets" / "fonts"
    if fonts_dir.exists():
        for ttf in sorted(fonts_dir.glob("*.ttf")):
            stem = _FONT_WEIGHT_RE.sub("", ttf.stem)
            display = camel_to_spaces(stem)
            options.append(FontOption(display_name=display, css_family=display, file_path=ttf))
    return options



# ── Ollama integration ─────────────────────────────────────────────────────

OLLAMA_BASE_URL = "http://localhost:11434"

RECOMMENDED_MODELS = [
    {
        "id": "aya-expanse:32b",
        "ram": "~20 GB",
        "note": "Best overall Arabic quality; requires Apple Silicon with 36 GB+ RAM",
    },
    {
        "id": "gemma3:27b",
        "ram": "~18 GB",
        "note": "Excellent quality; M1/M2 Pro or Max with 16 GB+ RAM",
    },
    {
        "id": "jwnder/jais-adaptive:7b",
        "ram": "~5 GB",
        "note": "Good Arabic support; works on any Mac with 8 GB+ RAM",
    },
    {
        "id": "gemma4:e4b",
        "ram": "~3 GB",
        "note": "Lightweight 4-bit model; fastest but less accurate on complex Arabic",
    },
]


def _find_ollama() -> str:
    """Return the path to the ollama binary, checking common locations."""
    import shutil
    # Try PATH first (works when launched from terminal)
    found = shutil.which("ollama")
    if found:
        return found
    # Common Homebrew locations (needed when launched as a .app bundle)
    for candidate in (
        "/opt/homebrew/bin/ollama",   # Apple Silicon Homebrew
        "/usr/local/bin/ollama",      # Intel Homebrew
        "/usr/bin/ollama",
    ):
        if Path(candidate).exists():
            return candidate
    return "ollama"  # fall back and let the OS report the error naturally


def _ollama_running() -> bool:
    try:
        req = _urllib_req.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
        with _urllib_req.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def _fetch_installed_models() -> list[str]:
    try:
        req = _urllib_req.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
        with _urllib_req.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def load_prompts() -> list[dict]:
    path = _BASE_DIR / "assets" / "prompts.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("actions", [])
    except Exception as exc:
        print(f"Warning: could not load prompts.json: {exc}")
        return []


_PROMPT_ACTIONS: list[dict] = []  # populated in main() after _BASE_DIR is set

# ── Anki export ───────────────────────────────────────────────────────────────
# This model ID is permanent — changing it would orphan existing Anki notes.
_ANKI_MODEL_ID = 1700000001


def _anki_model() -> "object":
    return _genanki.Model(
        _ANKI_MODEL_ID,
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


def build_anki_package(records: "list[SavedVocab]", output_path: Path) -> int:
    """Build an .apkg from vocab records. Returns the number of cards written.

    Cards are keyed by (book_id, normalized_word) so re-exporting the same
    word updates the existing Anki note rather than creating a duplicate.
    """
    if _genanki is None:
        raise RuntimeError("genanki is not installed. Run: pip install genanki")

    import zlib

    model = _anki_model()

    # Group records by book so each book becomes its own subdeck.
    from collections import defaultdict
    by_book: dict[str, list] = defaultdict(list)
    for r in records:
        by_book[r.book_id].append(r)

    decks = []
    for book_id, book_records in by_book.items():
        book_title = book_records[0].book_title or book_id
        deck_name = f"Kalima::{book_title}"
        # Stable deck ID derived from the deck name (zlib.crc32 is deterministic).
        deck_id = zlib.crc32(deck_name.encode()) & 0x7FFFFFFF
        deck = _genanki.Deck(deck_id, deck_name)

        for r in book_records:
            source = r.book_title or ""
            if r.chapter_title:
                source += f" · {r.chapter_title}"
            # Strip HTML from saved_definition for the card front field.
            import re as _re
            plain_def = _re.sub(r"<[^>]+>", "", r.saved_definition).strip()
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


@dataclass
class Chapter:
    idref: str
    title: str
    item_name: str
    file_path: Path


@dataclass
class SavedVocab:
    id: int
    book_id: str
    normalized_word: str
    word: str
    dictionary_term: str
    saved_definition: str
    dictionary_definition: str
    note: str
    book_title: str
    chapter_title: str
    chapter_index: int
    saved_at: str
    updated_at: str


@dataclass
class LookupRecord:
    clicked_word: str = ""
    normalized_word: str = ""
    term_used: str = ""
    dictionary_definition: str = ""
    book_id: str = ""
    book_title: str = ""
    chapter: str = ""
    chapter_index: int = -1
    saved: Optional[SavedVocab] = None
    displayed_definition: str = ""
    displayed_source: str = "Dictionary"


def app_now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def calculate_file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_output_path(base_dir: Path, item_name: str) -> Path:
    """Prevent path traversal when extracting EPUB resources."""
    clean_name = item_name.replace("\\", "/").lstrip("/")
    target = (base_dir / clean_name).resolve()
    base = base_dir.resolve()
    if base != target and base not in target.parents:
        fallback = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(item_name).name or "epub_item")
        target = base / fallback
    return target


def clean_lookup_word(word: str) -> str:
    word = (word or "").strip(TRIM_CHARS)
    word = word.replace("\u0640", "")  # tatweel
    word = re.sub(r"\s+", " ", word)
    return word.strip(TRIM_CHARS)


def normalize_arabic(word: str) -> str:
    word = clean_lookup_word(word)
    word = ARABIC_DIACRITICS_RE.sub("", word)
    word = word.replace("ـ", "")
    word = word.replace("ٱ", "ا").replace("آ", "ا").replace("أ", "ا").replace("إ", "ا")
    word = word.replace("ى", "ي")
    return word


def lookup_variants(word: str) -> list[str]:
    """Try conservative variants. Dictionary.app is often lemma-sensitive."""
    word = clean_lookup_word(word)
    no_diacritics = ARABIC_DIACRITICS_RE.sub("", word)
    normalized_alef = (
        no_diacritics.replace("أ", "ا")
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


def dictionary_lookup(word: str) -> tuple[str, str]:
    """
    Returns (term_used, definition). Uses Apple Dictionary Services.
    DCSCopyTextDefinition searches the active Dictionary.app dictionaries.
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
        except Exception as exc:
            return term, f"Dictionary lookup failed:\n{exc}"
        if result:
            return term, str(result)

    return word, "No definition found in the active macOS dictionaries."


def dictionary_definition_parts(definition: str) -> list[str]:
    """
    Apple Dictionary Services returns one plain-text string. Split it into readable
    lines that work both in the popup and in the editable save dialog.
    """
    raw = (definition or "").strip()
    if not raw:
        raw = "No definition available."

    nl = chr(10)
    text = " ".join(raw.split())
    text = text.replace("▸", nl + "▸ ")

    for number in range(1, 30):
        text = text.replace(" " + str(number) + " ", nl + str(number) + " ")

    for pos in ["noun", "verb", "adjective", "adverb", "plural", "preposition", "conjunction", "interjection"]:
        text = text.replace(" " + pos + " ", nl + pos + " ")

    parts = [line.strip() for line in text.split(nl) if line.strip()]
    return parts or [text]


def definition_text_to_editable_text(definition: str) -> str:
    return "\n".join(dictionary_definition_parts(definition))


def definition_text_to_readable_html(definition: str) -> str:
    """
    Format a Dictionary Services result for the read-only popup.
    """
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
        elif line.lower().split(" ", 1)[0] in ["noun", "verb", "adjective", "adverb", "plural", "preposition", "conjunction", "interjection"]:
            html_lines.append("<div class='pos'>" + escaped + "</div>")
        else:
            html_lines.append("<div>" + escaped + "</div>")
    return "".join(html_lines)


def looks_like_html(text: str) -> bool:
    sample = (text or "").strip().lower()
    return sample.startswith("<html") or sample.startswith("<!doctype") or "<body" in sample or "<div" in sample or "<p" in sample


def plain_text_to_user_html(text: str) -> str:
    lines = (text or "").splitlines() or [text or ""]
    return "".join("<div>" + html.escape(line) + "</div>" for line in lines)


def saved_definition_to_plain_text(text: str) -> str:
    """Handle newer plain-text entries and older rich-HTML entries cleanly."""
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
    return plain_text_to_user_html(saved_definition_to_plain_text(text))


def format_lookup_html(record: LookupRecord) -> str:
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
        note_block = f"""
        <div class="section">
            <div class="label">Saved note</div>
            <div class="note">{note}</div>
        </div>
        """

    return f"""
    <html>
    <head>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Geeza Pro', 'Arial', sans-serif;
            font-size: 17px;
            line-height: 1.38;
            margin: 0;
            padding: 0;
            color: #111;
            background: #fff;
        }}
        .section {{
            border-bottom: 1px solid #ddd;
            padding-bottom: 7px;
            margin-bottom: 8px;
        }}
        .label {{
            font-weight: 700;
            color: #555;
            margin-bottom: 3px;
            direction: ltr;
        }}
        .word {{
            font-size: 23px;
            font-weight: 800;
            direction: rtl;
            unicode-bidi: plaintext;
        }}
        .meta {{
            color: #666;
            margin-top: 2px;
        }}
        .saved {{
            color: #0b63ce;
            font-weight: 800;
        }}
        .unsaved {{
            color: #777;
            font-weight: 700;
        }}
        .note {{
            direction: rtl;
            unicode-bidi: plaintext;
            background: #f3f8ff;
            border: 1px solid #bcd7ff;
            border-radius: 8px;
            padding: 8px;
            white-space: pre-wrap;
        }}
        .entry-head {{
            font-size: 21px;
            font-weight: 700;
            margin-bottom: 7px;
            direction: rtl;
            unicode-bidi: plaintext;
        }}
        .pos {{
            font-weight: 700;
            color: #444;
            margin-top: 6px;
            margin-bottom: 2px;
            direction: ltr;
            unicode-bidi: plaintext;
        }}
        .sense {{
            margin-top: 6px;
            margin-bottom: 2px;
            font-weight: 600;
            direction: rtl;
            unicode-bidi: plaintext;
        }}
        .subentry {{
            margin-right: 18px;
            margin-top: 2px;
            direction: rtl;
            unicode-bidi: plaintext;
        }}
        .bar {{ color: #777; }}
        div {{
            white-space: normal;
            overflow-wrap: anywhere;
        }}
    </style>
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

def get_epub_item_content_safe(item) -> Optional[bytes]:
    """
    Some EPUBs list files in the manifest that are missing from the actual archive.
    Example: EPUB/Fonts/EversonMono.ttf.
    Skip those broken resources instead of crashing the whole reader.
    """
    try:
        return item.get_content()
    except KeyError as exc:
        print(f"Warning: missing EPUB resource skipped: {item.get_name()} ({exc})")
        return None
    except Exception as exc:
        print(f"Warning: could not read EPUB resource skipped: {item.get_name()} ({exc})")
        return None

class VocabularyStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS books (
                    book_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vocab (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id TEXT NOT NULL,
                    normalized_word TEXT NOT NULL,
                    word TEXT NOT NULL,
                    dictionary_term TEXT,
                    saved_definition TEXT NOT NULL,
                    dictionary_definition TEXT,
                    note TEXT,
                    book_title TEXT,
                    chapter_title TEXT,
                    chapter_index INTEGER,
                    saved_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(book_id, normalized_word),
                    FOREIGN KEY(book_id) REFERENCES books(book_id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vocab_book ON vocab(book_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vocab_word ON vocab(book_id, normalized_word)")

    def upsert_book(self, book_id: str, title: str, file_name: str, file_path: str) -> None:
        now = app_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO books(book_id, title, file_name, file_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    title=excluded.title,
                    file_name=excluded.file_name,
                    file_path=excluded.file_path,
                    updated_at=excluded.updated_at
                """,
                (book_id, title, file_name, file_path, now, now),
            )

    def saved_words_for_book(self, book_id: str) -> list[str]:
        if not book_id:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT normalized_word FROM vocab WHERE book_id = ? ORDER BY normalized_word",
                (book_id,),
            ).fetchall()
        return [str(row["normalized_word"]) for row in rows]

    def get_saved_word(self, book_id: str, normalized_word: str) -> Optional[SavedVocab]:
        if not book_id or not normalized_word:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM vocab WHERE book_id = ? AND normalized_word = ?",
                (book_id, normalized_word),
            ).fetchone()
        return self._row_to_vocab(row) if row else None

    def save_word(self, record: LookupRecord, saved_definition: str, note: str) -> None:
        now = app_now()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id, saved_at FROM vocab WHERE book_id = ? AND normalized_word = ?",
                (record.book_id, record.normalized_word),
            ).fetchone()
            saved_at = str(existing["saved_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO vocab(
                    book_id, normalized_word, word, dictionary_term,
                    saved_definition, dictionary_definition, note,
                    book_title, chapter_title, chapter_index,
                    saved_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(book_id, normalized_word) DO UPDATE SET
                    word=excluded.word,
                    dictionary_term=excluded.dictionary_term,
                    saved_definition=excluded.saved_definition,
                    dictionary_definition=excluded.dictionary_definition,
                    note=excluded.note,
                    book_title=excluded.book_title,
                    chapter_title=excluded.chapter_title,
                    chapter_index=excluded.chapter_index,
                    updated_at=excluded.updated_at
                """,
                (
                    record.book_id,
                    record.normalized_word,
                    record.clicked_word,
                    record.term_used,
                    saved_definition,
                    record.dictionary_definition,
                    note,
                    record.book_title,
                    record.chapter,
                    record.chapter_index,
                    saved_at,
                    now,
                ),
            )

    def delete_word(self, book_id: str, normalized_word: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM vocab WHERE book_id = ? AND normalized_word = ?",
                (book_id, normalized_word),
            )

    def vocab_for_export(self, book_id: Optional[str] = None) -> "list[SavedVocab]":
        with self.connect() as conn:
            if book_id:
                rows = conn.execute(
                    "SELECT * FROM vocab WHERE book_id = ? ORDER BY updated_at DESC",
                    (book_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM vocab ORDER BY book_title, updated_at DESC"
                ).fetchall()
        return [self._row_to_vocab(r) for r in rows]

    def export_csv(self, csv_path: Path) -> None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT saved_at, updated_at, word, normalized_word, dictionary_term,
                       saved_definition, note, book_title, chapter_title, dictionary_definition
                FROM vocab
                ORDER BY updated_at DESC
                """
            ).fetchall()

        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "saved_at",
                    "updated_at",
                    "word",
                    "normalized_word",
                    "dictionary_term",
                    "saved_definition",
                    "note",
                    "book_title",
                    "chapter_title",
                    "dictionary_definition",
                ],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row[key] for key in writer.fieldnames})

    def all_vocab(self, query: str = "") -> list[SavedVocab]:
        with self.connect() as conn:
            if query:
                q = f"%{query}%"
                rows = conn.execute(
                    """SELECT * FROM vocab
                       WHERE word LIKE ? OR note LIKE ? OR saved_definition LIKE ?
                       ORDER BY updated_at DESC""",
                    (q, q, q),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM vocab ORDER BY updated_at DESC"
                ).fetchall()
        return [self._row_to_vocab(r) for r in rows]

    def _row_to_vocab(self, row: sqlite3.Row) -> SavedVocab:
        return SavedVocab(
            id=int(row["id"]),
            book_id=str(row["book_id"]),
            normalized_word=str(row["normalized_word"]),
            word=str(row["word"]),
            dictionary_term=str(row["dictionary_term"] or ""),
            saved_definition=str(row["saved_definition"] or ""),
            dictionary_definition=str(row["dictionary_definition"] or ""),
            note=str(row["note"] or ""),
            book_title=str(row["book_title"] or ""),
            chapter_title=str(row["chapter_title"] or ""),
            chapter_index=int(row["chapter_index"] if row["chapter_index"] is not None else -1),
            saved_at=str(row["saved_at"]),
            updated_at=str(row["updated_at"]),
        )


class EpubBook:
    def __init__(self) -> None:
        self.path: Optional[Path] = None
        self.tempdir: Optional[tempfile.TemporaryDirectory[str]] = None
        self.chapters: list[Chapter] = []
        self.book_id: str = ""
        self.title: str = ""

    def close(self) -> None:
        self.chapters = []
        self.path = None
        self.book_id = ""
        self.title = ""
        if self.tempdir is not None:
            self.tempdir.cleanup()
            self.tempdir = None

    def open(self, epub_path: str | os.PathLike[str]) -> None:
        self.close()
        self.path = Path(epub_path)
        self.book_id = calculate_file_hash(self.path)
        self.tempdir = tempfile.TemporaryDirectory(prefix="kalima_epub_")
        out_dir = Path(self.tempdir.name)

        book = epub.read_epub(str(self.path))
        self.title = self._extract_book_title(book) or self.path.stem

        # Extract every EPUB item so chapter HTML can load local images/CSS/resources.
        for item in book.get_items():
            name = item.get_name() or f"item_{id(item)}"
            content = get_epub_item_content_safe(item)

            # Skip broken/missing resources such as missing fonts.
            if content is None:
                continue

            target = safe_output_path(out_dir, name)
            target.parent.mkdir(parents=True, exist_ok=True)

            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                content = self._prepare_html(content)

            target.write_bytes(content)

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

    def _prepare_html(self, content: bytes) -> bytes:
        try:
            soup = BeautifulSoup(content, "lxml-xml")
        except Exception:
            soup = BeautifulSoup(content, "html.parser")

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
        try:
            titles = book.get_metadata("DC", "title")
        except Exception:
            titles = []
        for title_item in titles:
            if title_item and title_item[0]:
                return str(title_item[0]).strip()
        return ""

    def _extract_title(self, content: bytes, fallback: str) -> str:
        try:
            soup = BeautifulSoup(content, "lxml-xml")
        except Exception:
            soup = BeautifulSoup(content, "html.parser")

        for selector in ("h1", "h2", "title"):
            tag = soup.find(selector)
            if tag:
                text = " ".join(tag.get_text(" ", strip=True).split())
                if text:
                    return text[:80]
        return Path(fallback).stem.replace("_", " ")[:80] or "Chapter"


class ReaderPage(QWebEnginePage):
    chapterNavigationRequested = pyqtSignal(str)
    wordLookupRequested = pyqtSignal(str)

    def acceptNavigationRequest(self, url: QUrl, nav_type: QWebEnginePage.NavigationType, is_main_frame: bool) -> bool:
        if url.scheme() == "lookup":
            parsed = urlparse(url.toString())
            qs = parse_qs(parsed.query)
            query_value = qs.get("value", [""])[0]
            word = clean_lookup_word(unquote(query_value))
            if word:
                self.wordLookupRequested.emit(word)
            return False

        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked and url.isLocalFile():
            self.chapterNavigationRequested.emit(url.toLocalFile())
            return True
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class ReaderView(QWebEngineView):
    wordClicked = pyqtSignal(str)
    aiActionRequested = pyqtSignal(str, str)   # action_id, selected_text
    customAiRequested = pyqtSignal(str, str)   # custom_prompt_template, selected_text
    translateRequested = pyqtSignal(str)        # selected_text

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt method name
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            return

        pos = event.position()
        QTimer.singleShot(80, lambda: self._lookup_at_position(int(pos.x()), int(pos.y())))

    def mouseDoubleClickEvent(self, event):  # noqa: N802 - Qt method name
        super().mouseDoubleClickEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        QTimer.singleShot(120, self._lookup_selected_text)

    def _lookup_selected_text(self) -> None:
        selected = clean_lookup_word(self.page().selectedText())
        if selected:
            self.wordClicked.emit(selected.split()[0])

    def _lookup_at_position(self, x: int, y: int) -> None:
        js = WORD_AT_POINT_JS.replace("__X__", str(x)).replace("__Y__", str(y))
        self.page().runJavaScript(js, self._emit_word_if_any)

    def _emit_word_if_any(self, payload: object) -> None:
        word = ""
        if isinstance(payload, dict):
            word = clean_lookup_word(str(payload.get("word", "")))
        elif isinstance(payload, str):
            word = clean_lookup_word(payload)
        if word:
            self.wordClicked.emit(word)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        selected = self.page().selectedText().strip()
        if not selected:
            super().contextMenuEvent(event)
            return
        menu = QMenu(self)
        copy_action = menu.addAction("Copy")
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(selected))
        translate_action = menu.addAction("Translate on Google")
        translate_action.triggered.connect(lambda: self.translateRequested.emit(selected))
        menu.addSeparator()
        claude_action = menu.addAction("Ask Claude")
        claude_action.triggered.connect(lambda: self._open_web_ai("claude", selected))
        chatgpt_action = menu.addAction("Ask ChatGPT")
        chatgpt_action.triggered.connect(lambda: self._open_web_ai("chatgpt", selected))

        if _PROMPT_ACTIONS:
            menu.addSeparator()
            ai_menu = menu.addMenu("Ask AI")
            for act in _PROMPT_ACTIONS:
                a = ai_menu.addAction(act["label"])
                a.triggered.connect(
                    lambda _, aid=act["id"], sel=selected: self.aiActionRequested.emit(aid, sel)
                )
            ai_menu.addSeparator()
            custom_a = ai_menu.addAction("Ask Custom Prompt…")
            custom_a.triggered.connect(lambda: self._ask_custom(selected))

        menu.exec(event.globalPos())

    def _ask_custom(self, selected: str) -> None:
        prompt, ok = QInputDialog.getMultiLineText(
            self,
            "Custom AI Prompt",
            "Enter your prompt. Use {text} to refer to the selected passage:",
            "Explain this in the context of Arabic literature:\n\n{text}",
        )
        if ok and prompt.strip():
            self.customAiRequested.emit(prompt.strip(), selected)

    @staticmethod
    def _open_google_translate(text: str) -> None:
        url = QUrl(f"https://translate.google.com/?sl=ar&tl=en&text={quote(text)}&op=translate")
        QDesktopServices.openUrl(url)

    @staticmethod
    def _open_web_ai(service: str, text: str) -> None:
        prompt = (
            f"Translate the following Arabic text to English and identify the most important vocabulary words with their meanings:\n\n{text}"
        )
        encoded = quote(prompt)
        if service == "claude":
            url = QUrl(f"https://claude.ai/new?q={encoded}")
        else:
            url = QUrl(f"https://chatgpt.com/?q={encoded}")
        QDesktopServices.openUrl(url)




class TranslatePanel(QWidget):
    """Sidebar that embeds a QWebEngineView to show Google Translate in-app."""

    closeRequested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(280)

        self._view = QWebEngineView()

        title = QLabel("Google Translate")
        title.setStyleSheet("font-weight: bold; font-size: 12px;")

        open_btn = QPushButton("Open in Browser")
        open_btn.setToolTip("Open the current URL in the default browser")
        open_btn.clicked.connect(self._open_in_browser)

        header = QHBoxLayout()
        header.setContentsMargins(8, 4, 4, 4)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(open_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self._view, 1)

    def load_url(self, url: QUrl) -> None:
        self._view.load(url)

    def _open_in_browser(self) -> None:
        QDesktopServices.openUrl(self._view.url())



class OllamaWorker(QThread):
    """Background thread that streams tokens from the Ollama /api/generate endpoint."""

    token_ready = pyqtSignal(str)
    finished = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, model: str, system: str, prompt: str) -> None:
        super().__init__()
        self._model = model
        self._system = system
        self._prompt = prompt
        self._abort = False

    def abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        payload = json.dumps({
            "model": self._model,
            "system": self._system,
            "prompt": self._prompt,
            "stream": True,
        }).encode()
        try:
            req = _urllib_req.Request(
                f"{OLLAMA_BASE_URL}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with _urllib_req.urlopen(req, timeout=300) as resp:
                for raw_line in resp:
                    if self._abort:
                        break
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    token = obj.get("response", "")
                    if token:
                        self.token_ready.emit(token)
                    if obj.get("done"):
                        break
        except Exception as exc:
            self.error_occurred.emit(str(exc))
        finally:
            self.finished.emit()


class _PullWorker(QThread):
    finished_ok = pyqtSignal()
    finished_err = pyqtSignal(str)

    def __init__(self, model_id: str, parent=None) -> None:
        super().__init__(parent)
        self._model_id = model_id

    def run(self) -> None:
        try:
            result = subprocess.run(
                [_find_ollama(), "pull", self._model_id],
                capture_output=True, text=True, timeout=1800,
            )
            if result.returncode == 0:
                self.finished_ok.emit()
            else:
                self.finished_err.emit(result.stderr.strip() or "Unknown error")
        except Exception as exc:
            self.finished_err.emit(str(exc))


class OllamaSetupDialog(QDialog):
    """Shown when Ollama is not reachable — explains installation and model options."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ollama Required")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("Ollama is not running")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(title)

        intro = QLabel(
            "The AI features in Kalima require <b>Ollama</b>, a free local AI runtime "
            "that runs language models entirely on your Mac — no internet connection or "
            "account needed after the initial model download."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        install_box = QFrame()
        install_box.setFrameShape(QFrame.Shape.StyledPanel)
        ib = QVBoxLayout(install_box)
        ib.addWidget(QLabel("<b>Install Ollama</b>"))
        ib.addWidget(QLabel("Option A — Homebrew (recommended):"))
        brew = QLabel("    brew install ollama")
        brew.setStyleSheet("font-family: monospace; padding: 2px 0;")
        ib.addWidget(brew)
        ib.addWidget(QLabel("Option B — Download the app directly:"))
        link = QLabel('<a href="https://ollama.com">https://ollama.com</a>')
        link.setOpenExternalLinks(True)
        ib.addWidget(link)
        ib.addWidget(QLabel("After installing, start the server with:"))
        serve = QLabel("    ollama serve")
        serve.setStyleSheet("font-family: monospace; padding: 2px 0;")
        ib.addWidget(serve)
        layout.addWidget(install_box)

        layout.addWidget(QLabel("<b>Recommended models</b> (choose based on your Mac's RAM):"))

        for m in RECOMMENDED_MODELS:
            row = QLabel(f"  •  <b>{m['id']}</b>  —  {m['ram']} RAM  —  {m['note']}")
            row.setWordWrap(True)
            layout.addWidget(row)

        note = QLabel(
            "Smaller models are faster but less accurate on complex Arabic text such as "
            "classical prose or poetry. Larger models give better morphological analysis "
            "and more natural translations."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(note)

        btn_row = QHBoxLayout()
        check_btn = QPushButton("Check Again")
        check_btn.clicked.connect(self._check_again)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(check_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _check_again(self) -> None:
        if _ollama_running():
            self.accept()
        else:
            QMessageBox.warning(self, "Not found", "Ollama is still not reachable at localhost:11434.")


class ModelManagerDialog(QDialog):
    """Lists recommended models, shows install status, and offers to pull missing ones."""

    def __init__(self, installed: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage AI Models")
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(QLabel("<b>Recommended models for Arabic</b>"))
        layout.addWidget(QLabel(
            "Click Pull to download a model. Downloads may take several minutes."
        ))

        for m in RECOMMENDED_MODELS:
            is_installed = any(m["id"] in name for name in installed)
            row = QHBoxLayout()
            name_lbl = QLabel(f"<b>{m['id']}</b>  ({m['ram']})")
            name_lbl.setMinimumWidth(270)
            status_lbl = QLabel("✓ Installed" if is_installed else "Not installed")
            status_lbl.setStyleSheet("color: green;" if is_installed else "color: gray;")
            pull_btn = QPushButton("Pull")
            pull_btn.setEnabled(not is_installed)
            pull_btn.clicked.connect(
                lambda _, mid=m["id"], sl=status_lbl, pb=pull_btn: self._pull(mid, sl, pb)
            )
            row.addWidget(name_lbl)
            row.addWidget(status_lbl)
            row.addStretch()
            row.addWidget(pull_btn)
            layout.addLayout(row)

        layout.addSpacing(6)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _pull(self, model_id: str, status_lbl: "QLabel", pull_btn: "QPushButton") -> None:
        pull_btn.setEnabled(False)
        status_lbl.setText("Downloading… (may take several minutes)")
        status_lbl.setStyleSheet("color: orange;")
        worker = _PullWorker(model_id, self)
        worker.finished_ok.connect(lambda: self._pull_done(status_lbl, True))
        worker.finished_err.connect(lambda err: self._pull_done(status_lbl, False, err))
        worker.start()
        self._current_pull = worker

    def _pull_done(self, status_lbl: "QLabel", ok: bool, err: str = "") -> None:
        if ok:
            status_lbl.setText("✓ Installed")
            status_lbl.setStyleSheet("color: green;")
        else:
            status_lbl.setText(f"Failed: {err}")
            status_lbl.setStyleSheet("color: red;")


class OllamaPanel(QWidget):
    """Resizable side panel that runs AI prompts via Ollama and streams the response."""

    def __init__(self, settings: "QSettings", parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._worker: Optional[OllamaWorker] = None
        self.setMinimumWidth(240)

        header = QLabel("AI Assistant")
        header.setStyleSheet("font-weight: bold; font-size: 13px;")

        manage_btn = QPushButton("Models…")
        manage_btn.setToolTip("Manage recommended models")
        manage_btn.clicked.connect(self._manage_models)

        header_row = QHBoxLayout()
        header_row.addWidget(header)
        header_row.addStretch()
        header_row.addWidget(manage_btn)

        self.model_combo = QComboBox()
        self.model_combo.setToolTip("Active Ollama model")
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedWidth(28)
        refresh_btn.setToolTip("Refresh model list")
        refresh_btn.clicked.connect(self.refresh_models)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(refresh_btn)

        self._action_label = QLabel("")
        self._action_label.setStyleSheet("color: gray; font-size: 11px;")
        self._action_label.setWordWrap(True)

        self.response_view = QTextEdit()
        self.response_view.setReadOnly(True)
        self.response_view.setPlaceholderText(
            "Select text in the reader and right-click → Ask AI…"
        )

        self._stop_btn = QPushButton("Stop generation")
        self._stop_btn.setVisible(False)
        self._stop_btn.clicked.connect(self._stop_generation)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addLayout(header_row)
        layout.addLayout(model_row)
        layout.addWidget(self._action_label)
        layout.addWidget(self.response_view, 1)
        layout.addWidget(self._stop_btn)

        self.refresh_models()

    def refresh_models(self) -> None:
        models = _fetch_installed_models()
        prev = self.model_combo.currentText()
        self.model_combo.clear()
        if models:
            self.model_combo.addItems(models)
            idx = self.model_combo.findText(prev)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            saved = str(self._settings.value("ai_model", ""))
            if saved:
                idx2 = self.model_combo.findText(saved)
                if idx2 >= 0:
                    self.model_combo.setCurrentIndex(idx2)
        else:
            self.model_combo.addItem("(no models — is Ollama running?)")
        self.model_combo.currentTextChanged.connect(
            lambda t: self._settings.setValue("ai_model", t)
        )

    def current_model(self) -> str:
        return self.model_combo.currentText()

    def run_action(self, action_id: str, text: str, custom_prompt: str = "") -> None:
        if not _ollama_running():
            dlg = OllamaSetupDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            self.refresh_models()

        if action_id == "custom":
            system = "You are a helpful Arabic language assistant."
            if "{text}" in custom_prompt:
                prompt = custom_prompt.replace("{text}", text)
            else:
                prompt = custom_prompt + "\n\n" + text
            label = custom_prompt[:60] + ("…" if len(custom_prompt) > 60 else "")
        else:
            action = next((a for a in _PROMPT_ACTIONS if a["id"] == action_id), None)
            if action is None:
                return
            system = action.get("system", "")
            prompt = action["user_template"].replace("{text}", text)
            label = action["label"]

        model = self.current_model()
        if not model or model.startswith("("):
            QMessageBox.warning(self, "No model selected", "Please select a valid model from the dropdown.")
            return

        preview = text[:60] + ("…" if len(text) > 60 else "")
        self._action_label.setText(f"{label}  ·  “{preview}”")
        self.response_view.clear()
        self._stop_btn.setVisible(True)

        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait()

        self._worker = OllamaWorker(model=model, system=system, prompt=prompt)
        self._worker.token_ready.connect(self._append_token)
        self._worker.finished.connect(self._on_finished)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    def _append_token(self, token: str) -> None:
        cursor = self.response_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(token)
        self.response_view.setTextCursor(cursor)
        self.response_view.ensureCursorVisible()

    def _stop_generation(self) -> None:
        if self._worker:
            self._worker.abort()
        self._stop_btn.setVisible(False)

    def _on_finished(self) -> None:
        self._stop_btn.setVisible(False)

    def _on_error(self, msg: str) -> None:
        self.response_view.append(f"\n\n[Error: {msg}]")
        self._stop_btn.setVisible(False)

    def _manage_models(self) -> None:
        installed = _fetch_installed_models()
        dlg = ModelManagerDialog(installed, self)
        dlg.exec()
        self.refresh_models()


class SaveVocabDialog(QDialog):
    deletedRequested = pyqtSignal(object)

    def __init__(self, record: LookupRecord, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.record = record
        self.setWindowTitle("Save vocabulary word")
        self.resize(720, 560)

        word_label = QLabel(record.clicked_word)
        word_label.setStyleSheet("font-size: 28px; font-weight: 800;")
        word_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        meta = QLabel(f"Book: {record.book_title}\nChapter: {record.chapter}")
        meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.definition_edit = QTextEdit()
        self.definition_edit.setAcceptRichText(False)
        self.definition_edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.definition_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.definition_edit.setPlaceholderText("Edit the definition before saving…")
        self.definition_edit.setStyleSheet("font-size: 17px; line-height: 1.35;")
        initial_definition = record.saved.saved_definition if record.saved else record.dictionary_definition
        if record.saved:
            self.definition_edit.setPlainText(saved_definition_to_plain_text(initial_definition or ""))
        else:
            self.definition_edit.setPlainText(definition_text_to_editable_text(initial_definition or ""))

        self.note_edit = QTextEdit()
        self.note_edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.note_edit.setMaximumHeight(110)
        self.note_edit.setPlaceholderText("Optional note, memory aid, grammar note, example, etc.")
        self.note_edit.setPlainText(record.saved.note if record.saved else "")

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        self.delete_btn = QPushButton("Delete saved word")
        self.delete_btn.setEnabled(record.saved is not None)
        self.delete_btn.clicked.connect(self._delete_clicked)

        button_row = QHBoxLayout()
        button_row.addWidget(self.delete_btn)
        button_row.addStretch(1)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Word"))
        layout.addWidget(word_label)
        layout.addWidget(meta)
        layout.addWidget(QLabel("Saved definition — edit, delete, or add anything before saving. Line breaks are kept."))
        layout.addWidget(self.definition_edit)
        layout.addWidget(QLabel("Optional note"))
        layout.addWidget(self.note_edit)
        layout.addLayout(button_row)

    def saved_definition(self) -> str:
        # Store clean editable text. The popup converts line breaks back into readable HTML.
        return self.definition_edit.toPlainText().strip()

    def saved_definition_plain_text(self) -> str:
        return self.definition_edit.toPlainText().strip()

    def note(self) -> str:
        return self.note_edit.toPlainText().strip()

    def _delete_clicked(self) -> None:
        if self.record.saved is None:
            return
        
        # delete without confirmation dialog:
        self.deletedRequested.emit(self.record)
        self.reject()
        
        # optional confirmation dialog before deleting a saved word:
        # reply = QMessageBox.question(
        #     self,
        #     "Delete saved word?",
        #     f"Delete saved vocabulary entry for '{self.record.clicked_word}'?",
        #     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        #     QMessageBox.StandardButton.No,
        # )
        # if reply == QMessageBox.StandardButton.Yes:
        #     self.deletedRequested.emit(self.record)
        #     self.reject()
        


class AnkiExportDialog(QDialog):
    """Scope + destination picker for Anki .apkg export."""

    def __init__(
        self,
        vocab_store: "VocabularyStore",
        current_book_id: str,
        current_book_title: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export to Anki")
        self.setMinimumWidth(440)
        self._store = vocab_store
        self._current_book_id = current_book_id
        self._current_book_title = current_book_title

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel("<b>Export vocabulary to Anki (.apkg)</b>"))
        layout.addWidget(QLabel(
            "Cards are keyed by word so re-importing updates existing notes "
            "rather than creating duplicates."
        ))

        # ── Scope ──────────────────────────────────────────────────────────
        scope_box = QFrame()
        scope_box.setFrameShape(QFrame.Shape.StyledPanel)
        sb = QVBoxLayout(scope_box)
        self._rb_current = None

        from PyQt6.QtWidgets import QRadioButton, QButtonGroup
        self._scope_group = QButtonGroup(self)

        if current_book_id:
            self._rb_current = QRadioButton(
                f"Current book only  ({current_book_title or current_book_id})"
            )
            self._rb_current.setChecked(True)
            self._scope_group.addButton(self._rb_current, 0)
            sb.addWidget(self._rb_current)

        rb_all = QRadioButton("All books")
        if not current_book_id:
            rb_all.setChecked(True)
        self._scope_group.addButton(rb_all, 1)
        sb.addWidget(rb_all)
        layout.addWidget(scope_box)

        # ── Destination ────────────────────────────────────────────────────
        dest_row = QHBoxLayout()
        self._dest_edit = QLineEdit()
        default_name = (
            f"Kalima - {current_book_title}.apkg" if current_book_id else "Kalima.apkg"
        )
        self._dest_edit.setText(
            str(Path.home() / "Desktop" / default_name)
        )
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)
        dest_row.addWidget(self._dest_edit, 1)
        dest_row.addWidget(browse_btn)
        layout.addWidget(QLabel("Save as:"))
        layout.addLayout(dest_row)

        # Update filename when scope changes
        self._scope_group.idToggled.connect(self._update_filename)

        # ── Buttons ────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        export_btn = QPushButton("Export")
        export_btn.setDefault(True)
        export_btn.clicked.connect(self._do_export)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(export_btn)
        layout.addLayout(btn_row)

    def _update_filename(self, btn_id: int, checked: bool) -> None:
        if not checked:
            return
        if btn_id == 0 and self._current_book_title:
            name = f"Kalima - {self._current_book_title}.apkg"
        else:
            name = "Kalima.apkg"
        folder = Path(self._dest_edit.text()).parent
        self._dest_edit.setText(str(folder / name))

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Anki deck", self._dest_edit.text(),
            "Anki Package (*.apkg);;All files (*)",
        )
        if path:
            if not path.endswith(".apkg"):
                path += ".apkg"
            self._dest_edit.setText(path)

    def _do_export(self) -> None:
        book_id = (
            self._current_book_id
            if (self._rb_current and self._rb_current.isChecked())
            else None
        )
        records = self._store.vocab_for_export(book_id)
        if not records:
            QMessageBox.information(self, "Nothing to export", "No vocabulary words found.")
            return

        output = Path(self._dest_edit.text().strip())
        if not output.suffix:
            output = output.with_suffix(".apkg")
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            count = build_anki_package(records, output)
            QMessageBox.information(
                self,
                "Export complete",
                f"Exported {count} card{'s' if count != 1 else ''} to:\n{output}\n\n"
                "Double-click the file in Finder to import into Anki.\n"
                "Re-importing will update existing cards automatically.",
            )
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))



class VocabBrowserDialog(QDialog):
    def __init__(self, vocab_store: "VocabularyStore", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.vocab_store = vocab_store
        self.setWindowTitle("Vocabulary Browser")
        self.resize(860, 560)

        self._entries: list[SavedVocab] = []

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter by word, definition, or note…")
        self.search_box.textChanged.connect(self._refresh)

        self.count_label = QLabel()

        self.word_list = QListWidget()
        self.word_list.itemSelectionChanged.connect(self._on_selection)
        self.word_list.itemDoubleClicked.connect(self._edit_selected)

        self.detail_word = QLabel()
        self.detail_word.setStyleSheet("font-size: 26px; font-weight: 800;")
        self.detail_word.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.detail_word.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.detail_book = QLabel()
        self.detail_book.setWordWrap(True)

        self.detail_def = QTextEdit()
        self.detail_def.setReadOnly(True)
        self.detail_def.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.detail_def.setStyleSheet("font-size: 15px;")

        self.detail_note = QLabel()
        self.detail_note.setWordWrap(True)
        self.detail_note.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.detail_note.setStyleSheet("color: #555;")

        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(self._edit_selected)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete_selected)

        anki_btn = QPushButton("Export to Anki…")
        anki_btn.setToolTip("Export vocabulary as an Anki .apkg deck")
        anki_btn.clicked.connect(self._export_anki)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        search_row.addWidget(self.search_box)

        left_layout = QVBoxLayout()
        left_layout.addLayout(search_row)
        left_layout.addWidget(self.count_label)
        left_layout.addWidget(self.word_list)
        left_widget = QWidget()
        left_widget.setLayout(left_layout)
        left_widget.setMaximumWidth(320)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.detail_word)
        right_layout.addWidget(self.detail_book)
        right_layout.addWidget(QLabel("Definition:"))
        right_layout.addWidget(self.detail_def)
        right_layout.addWidget(QLabel("Note:"))
        right_layout.addWidget(self.detail_note)
        right_layout.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(anki_btn)
        btn_row.addWidget(close_btn)
        right_layout.addLayout(btn_row)

        right_widget = QWidget()
        right_widget.setLayout(right_layout)

        splitter = QSplitter()
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(splitter)

        self._refresh()

    def _refresh(self) -> None:
        query = self.search_box.text().strip()
        self._entries = self.vocab_store.all_vocab(query)
        self.word_list.clear()
        for v in self._entries:
            self.word_list.addItem(f"{v.word}  —  {v.book_title or 'Unknown book'}")
        n = len(self._entries)
        self.count_label.setText(f"{n} word{'s' if n != 1 else ''}")
        self._clear_detail()

    def _clear_detail(self) -> None:
        self.detail_word.clear()
        self.detail_book.clear()
        self.detail_def.clear()
        self.detail_note.clear()

    def _on_selection(self) -> None:
        v = self._current_vocab()
        if v is None:
            self._clear_detail()
            return
        self.detail_word.setText(v.word)
        book_info = v.book_title or "Unknown book"
        if v.chapter_title:
            book_info += f"  ·  {v.chapter_title}"
        self.detail_book.setText(book_info)
        self.detail_def.setPlainText(saved_definition_to_plain_text(v.saved_definition))
        self.detail_note.setText(v.note or "")

    def _current_vocab(self) -> Optional[SavedVocab]:
        items = self.word_list.selectedItems()
        if not items:
            return None
        idx = self.word_list.row(items[0])
        return self._entries[idx] if 0 <= idx < len(self._entries) else None

    def _edit_selected(self, *_: object) -> None:
        v = self._current_vocab()
        if v is None:
            return
        record = LookupRecord(
            clicked_word=v.word,
            normalized_word=v.normalized_word,
            term_used=v.dictionary_term,
            dictionary_definition=v.dictionary_definition,
            book_id=v.book_id,
            book_title=v.book_title,
            chapter=v.chapter_title,
            chapter_index=v.chapter_index,
            saved=v,
            displayed_definition=v.saved_definition,
            displayed_source="Saved definition",
        )
        dlg = SaveVocabDialog(record, self)
        dlg.deletedRequested.connect(self._on_deleted)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.vocab_store.save_word(record, saved_definition=dlg.saved_definition(), note=dlg.note())
            self._refresh()

    def _on_deleted(self, record_obj: object) -> None:
        if isinstance(record_obj, LookupRecord):
            self.vocab_store.delete_word(record_obj.book_id, record_obj.normalized_word)
            self._refresh()

    def _delete_selected(self) -> None:
        v = self._current_vocab()
        if v is None:
            return
        reply = QMessageBox.question(
            self,
            "Delete word?",
            f"Delete saved word '{v.word}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.vocab_store.delete_word(v.book_id, v.normalized_word)
            self._refresh()

    def _export_anki(self) -> None:
        if _genanki is None:
            QMessageBox.critical(
                self, "genanki not installed",
                "Install it with:\n\n    pip install genanki\n\nthen restart Kalima.",
            )
            return
        # Pass the current book context if the parent window has one.
        book_id = ""
        book_title = ""
        mw = self.parent()
        if mw and hasattr(mw, "book") and mw.book.path:
            book_id = mw.book.book_id
            book_title = mw.book.title
        dlg = AnkiExportDialog(self.vocab_store, book_id, book_title, self)
        dlg.exec()


class LookupPopup(QFrame):
    saveRequested = pyqtSignal(object)
    closed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        # self.setMinimumWidth(650)
        # self.setMaximumWidth(980)
        # self.setMinimumHeight(430)
        # self.setMaximumHeight(760)
        self.setMinimumWidth(500)
        self.setMaximumWidth(550)
        self.setMinimumHeight(400)
        self.setMaximumHeight(430)

        self.title = QLabel()
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.title.setStyleSheet("font-weight: 700; font-size: 16px;")

        self.definition = QTextEdit()
        self.definition.setReadOnly(True)
        self.definition.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.definition.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.definition.setStyleSheet("font-size: 17px; line-height: 1.35;")

        self.save_btn = QPushButton("Save / edit word")
        self.save_btn.clicked.connect(self._emit_save)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)

        open_dictionary_btn = QPushButton("Open in Dictionary.app")
        open_dictionary_btn.clicked.connect(self.open_in_dictionary_app)

        button_row = QHBoxLayout()
        button_row.addWidget(open_dictionary_btn)
        button_row.addWidget(self.save_btn)
        button_row.addStretch(1)
        button_row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        layout.addWidget(self.title)
        layout.addWidget(self.definition)
        layout.addLayout(button_row)

        self._current_word = ""
        self._current_record: Optional[LookupRecord] = None

    def show_lookup(self, record: LookupRecord) -> None:
        self._current_record = record
        clicked_word = record.clicked_word
        term_used = record.term_used
        self._current_word = term_used or clicked_word
        self.save_btn.setText("Edit saved word" if record.saved else "Save word")

        if term_used and term_used != clicked_word:
            self.title.setText(f"{clicked_word}  →  {term_used}")
        else:
            self.title.setText(clicked_word)

        self.definition.setHtml(format_lookup_html(record))
        self.resize(820, 620)
        self.adjustSize()

        cursor_pos = QCursor.pos()
        desired_x = cursor_pos.x() + 14
        desired_y = cursor_pos.y() + 14

        screen = QGuiApplication.screenAt(cursor_pos) or QGuiApplication.primaryScreen()
        if screen is not None:
            bounds = screen.availableGeometry()
            width = min(max(self.width(), self.minimumWidth()), self.maximumWidth())
            height = min(max(self.height(), self.minimumHeight()), self.maximumHeight())
            desired_x = max(bounds.left() + 8, min(desired_x, bounds.right() - width - 8))
            desired_y = max(bounds.top() + 8, min(desired_y, bounds.bottom() - height - 8))
            self.resize(width, height)

        self.move(desired_x, desired_y)
        self.show()
        self.raise_()
        self.activateWindow()

    def _emit_save(self) -> None:
        if self._current_record is not None:
            self.saveRequested.emit(self._current_record)

    def open_in_dictionary_app(self) -> None:
        if not self._current_word:
            return
        os.system(f"open 'dict://{quote(self._current_word)}' >/dev/null 2>&1 &")

    def hideEvent(self, event):
        self.closed.emit()
        super().hideEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Kalima")
        self.resize(1200, 820)

        self.settings = QSettings(APP_ORG, APP_NAME)
        self.vocab_store = VocabularyStore(VOCAB_DB_PATH)
        self.book = EpubBook()
        self.current_chapter_index = -1
        self.zoom_factor = float(self.settings.value("zoom_factor", 1.0))
        self.lookup_mode = str(self.settings.value("lookup_mode", "popup"))  # popup | dictionary_app
        self.definition_mode = str(self.settings.value("definition_mode", "dictionary"))  # dictionary | saved
        self.hide_tashkeel = str(self.settings.value("hide_tashkeel", "false")) == "true"
        self.dark_mode = str(self.settings.value("dark_mode", "false")) == "true"
        self.toolbar_style = str(self.settings.value("toolbar_style", "icon"))
        self.translate_in_app = str(self.settings.value("translate_in_app", "false")) == "true"
        self._font_options: list[FontOption] = load_font_options()
        self.reader_font = str(self.settings.value("reader_font", "System Default"))
        self._recent_files: list[str] = self._load_recent_files()

        self.chapter_list = QListWidget()
        self.chapter_list.setMaximumWidth(320)
        self.chapter_list.currentRowChanged.connect(self.load_chapter)

        self.reader_page = ReaderPage(self)
        self.reader_page.chapterNavigationRequested.connect(self._sync_chapter_from_path)
        self.reader_page.wordLookupRequested.connect(self.lookup_word)

        self.reader_view = ReaderView()
        self.reader_view.setPage(self.reader_page)
        self.reader_view.setZoomFactor(self.zoom_factor)
        self.reader_view.wordClicked.connect(self.lookup_word)
        self.reader_view.loadFinished.connect(self.install_word_click_handler)
        self.reader_view.aiActionRequested.connect(self._handle_ai_action)
        self.reader_view.customAiRequested.connect(self._handle_custom_ai)
        self.reader_view.translateRequested.connect(self._handle_translate)

        self._translate_panel = TranslatePanel()
        self._translate_panel.setVisible(False)

        self._ai_panel = OllamaPanel(self.settings)
        self._ai_panel.setVisible(False)

        self._splitter = QSplitter()
        self._splitter.addWidget(self.chapter_list)
        self._splitter.addWidget(self.reader_view)
        self._splitter.addWidget(self._translate_panel)
        self._splitter.addWidget(self._ai_panel)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setStretchFactor(3, 0)
        self.setCentralWidget(self._splitter)

        self.lookup_popup = LookupPopup(self)
        self.lookup_popup.saveRequested.connect(self.open_save_vocabulary_dialog)
        self.lookup_popup.closed.connect(self.remove_active_highlight)
        self.find_box = QLineEdit()
        self.find_box.setPlaceholderText("Find in chapter…")
        self.find_box.returnPressed.connect(self.find_next)

        self._build_toolbar()
        self._build_menu_bar()
        self.setStatusBar(QStatusBar())
        self._progress_label = QLabel()
        self._progress_label.setStyleSheet("padding-right: 8px; color: gray;")
        self.statusBar().addPermanentWidget(self._progress_label)
        self.reader_page.scrollPositionChanged.connect(self._on_scroll_changed)
        QApplication.instance().paletteChanged.connect(self._refresh_toolbar_icons)

        last_path = self.settings.value("last_epub_path", "")
        if last_path and Path(str(last_path)).exists():
            try:
                self.open_epub(str(last_path), restore_position=True)
            except Exception:
                pass

    def closeEvent(self, event):  # noqa: N802 - Qt method name
        self.settings.setValue("zoom_factor", self.zoom_factor)
        self.settings.setValue("definition_mode", self.definition_mode)
        self.settings.setValue("dark_mode", "true" if self.dark_mode else "false")
        self.settings.setValue("toolbar_style", self.toolbar_style)
        self.settings.setValue("reader_font", self.reader_font)
        self.settings.setValue("translate_in_app", "true" if self.translate_in_app else "false")
        if self.book.path:
            self.settings.setValue("last_epub_path", str(self.book.path))
            self.settings.setValue(f"last_chapter::{self.book.path}", self.current_chapter_index)
        self.book.close()
        super().closeEvent(event)

    def _build_toolbar(self) -> None:
        self._toolbar = QToolBar("Main")
        toolbar = self._toolbar          # local alias for brevity
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)

        # Helper: create an action with an icon and register the icon name so
        # _refresh_toolbar_icons() can re-render it when the OS appearance changes.
        def _ia(icon_name: str, text: str) -> QAction:
            a = QAction(svg_icon(icon_name), text, self)
            a.setObjectName(icon_name)
            return a

        self.open_action = _ia("open-epub", "Open EPUB")
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.choose_epub)
        toolbar.addAction(self.open_action)

        toolbar.addSeparator()

        prev_action = _ia("previous", "Previous")
        prev_action.setShortcut(QKeySequence.StandardKey.MoveToPreviousChar)
        prev_action.triggered.connect(self.previous_chapter)
        toolbar.addAction(prev_action)

        next_action = _ia("next", "Next")
        next_action.setShortcut(QKeySequence.StandardKey.MoveToNextChar)
        next_action.triggered.connect(self.next_chapter)
        toolbar.addAction(next_action)

        toolbar.addSeparator()

        zoom_out_action = _ia("font-decrease", "Zoom Out")
        zoom_out_action.setShortcut(QKeySequence.StandardKey.ZoomOut)
        zoom_out_action.triggered.connect(self.zoom_out)
        toolbar.addAction(zoom_out_action)

        zoom_in_action = _ia("font-increase", "Zoom In")
        zoom_in_action.setShortcut(QKeySequence.StandardKey.ZoomIn)
        zoom_in_action.triggered.connect(self.zoom_in)
        toolbar.addAction(zoom_in_action)

        reset_zoom_action = _ia("reset", "Reset Zoom")
        reset_zoom_action.triggered.connect(self.reset_zoom)
        toolbar.addAction(reset_zoom_action)

        toolbar.addSeparator()

        self.font_combo = QComboBox()
        self.font_combo.setMaximumWidth(170)
        self.font_combo.setToolTip("Reader font")
        for opt in self._font_options:
            self.font_combo.addItem(opt.display_name)
        current_idx = next(
            (i for i, o in enumerate(self._font_options) if o.display_name == self.reader_font), 0
        )
        self.font_combo.setCurrentIndex(current_idx)
        self.font_combo.currentIndexChanged.connect(self._on_font_changed)
        toolbar.addWidget(self.font_combo)

        toolbar.addSeparator()

        self.tashkeel_action = _ia("hide-tashkeel", self._tashkeel_label())
        self.tashkeel_action.setShortcut(QKeySequence("Ctrl+Shift+H"))
        self.tashkeel_action.setToolTip("Toggle Arabic tashkeel/harakat display (⌘⇧H)")
        self.tashkeel_action.triggered.connect(self.toggle_tashkeel)
        toolbar.addAction(self.tashkeel_action)

        toolbar.addSeparator()

        self._search_icon_label = QLabel()
        self._search_icon_label.setPixmap(svg_icon("search", size=18).pixmap(QSize(18, 18)))
        self._search_icon_label.setContentsMargins(4, 0, 2, 0)
        toolbar.addWidget(self._search_icon_label)
        self.find_box.setMaximumWidth(260)
        self.find_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        toolbar.addWidget(self.find_box)

        find_next_action = _ia("find-next", "Find Next")
        find_next_action.setShortcut(QKeySequence.StandardKey.FindNext)
        find_next_action.triggered.connect(self.find_next)
        toolbar.addAction(find_next_action)

        toolbar.addSeparator()

        self.lookup_mode_action = _ia("lookup-popup", self._lookup_mode_label())
        self.lookup_mode_action.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self.lookup_mode_action.setToolTip(
            "Toggle lookup behavior: in-app popup or macOS Dictionary.app (⌘⇧L). "
            "True macOS Force Click popover is not reliably exposed through PyQt WebEngine, "
            "so Dictionary.app mode uses dict://word."
        )
        self.lookup_mode_action.triggered.connect(self.toggle_lookup_mode)
        toolbar.addAction(self.lookup_mode_action)

        self.definition_mode_action = _ia("definition-saved", self._definition_mode_label())
        self.definition_mode_action.setToolTip(
            "When a word is already saved, choose whether clicking it shows your saved definition or a fresh dictionary lookup."
        )
        self.definition_mode_action.triggered.connect(self.toggle_definition_mode)
        toolbar.addAction(self.definition_mode_action)

        self.dark_mode_action = _ia("dark-mode", self._dark_mode_label())
        self.dark_mode_action.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.dark_mode_action.setToolTip("Toggle reader dark mode (⌘⇧D)")
        self.dark_mode_action.triggered.connect(self.toggle_dark_mode)
        toolbar.addAction(self.dark_mode_action)

        vocab_browser_action = _ia("browse-vocab", "Browse Vocab")
        vocab_browser_action.setShortcut(QKeySequence("Ctrl+Shift+V"))
        vocab_browser_action.setToolTip("Browse and search saved vocabulary (⌘⇧V)")
        vocab_browser_action.triggered.connect(self.open_vocab_browser)
        toolbar.addAction(vocab_browser_action)

        self.export_action = _ia("export-vocab-csv", "Export Vocab CSV")
        self.export_action.setToolTip(f"Exports vocabulary from SQLite to {VOCAB_CSV_PATH}")
        self.export_action.triggered.connect(self.export_vocab_csv)
        toolbar.addAction(self.export_action)

        # Apply persisted toolbar style
        self.set_toolbar_style(self.toolbar_style, save=False)

    def _build_menu_bar(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.open_action)
        self._recent_menu: QMenu = file_menu.addMenu("Open Recent")
        self._update_recent_files_menu()
        file_menu.addSeparator()
        file_menu.addAction(self.export_action)

        view_menu = self.menuBar().addMenu("View")

        self._ai_panel_action = view_menu.addAction("Show AI Panel")
        self._ai_panel_action.setCheckable(True)
        self._ai_panel_action.setChecked(False)
        self._ai_panel_action.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self._ai_panel_action.toggled.connect(self._toggle_ai_panel)

        self._translate_in_app_action = view_menu.addAction("Google Translate: Open in App Panel")
        self._translate_in_app_action.setCheckable(True)
        self._translate_in_app_action.setChecked(self.translate_in_app)
        self._translate_in_app_action.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self._translate_in_app_action.toggled.connect(self._toggle_translate_mode)
        view_menu.addSeparator()

        toolbar_menu = view_menu.addMenu("Toolbar Style")
        style_group = QActionGroup(self)
        style_group.setExclusive(True)
        for label, key in [
            ("Icons Only", "icon"),
            ("Icons and Text", "icon_text"),
            ("Text Only", "text"),
        ]:
            a = QAction(label, self)
            a.setCheckable(True)
            a.setChecked(key == self.toolbar_style)
            a.triggered.connect(lambda checked, k=key: self.set_toolbar_style(k))
            style_group.addAction(a)
            toolbar_menu.addAction(a)

    def choose_epub(self) -> None:
        last_dir = str(self.settings.value("last_open_dir", str(Path.home())))
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open EPUB",
            last_dir,
            "EPUB files (*.epub);;All files (*)",
        )
        if path:
            self.settings.setValue("last_open_dir", str(Path(path).parent))
            self.open_epub(path, restore_position=False)

    def open_epub(self, path: str, restore_position: bool = False) -> None:
        try:
            self.book.open(path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not open EPUB", str(exc))
            return

        self.vocab_store.upsert_book(
            book_id=self.book.book_id,
            title=self.book.title,
            file_name=self.book.path.name if self.book.path else "",
            file_path=str(self.book.path) if self.book.path else "",
        )

        self.chapter_list.blockSignals(True)
        self.chapter_list.clear()
        for chapter in self.book.chapters:
            self.chapter_list.addItem(chapter.title)
        self.chapter_list.blockSignals(False)

        self.setWindowTitle(f"Kalima — {self.book.title or Path(path).name}")
        self.settings.setValue("last_epub_path", path)
        self._add_to_recent_files(path)

        chapter_index = 0
        if restore_position:
            saved = self.settings.value(f"last_chapter::{Path(path)}", 0)
            try:
                chapter_index = max(0, min(int(saved), len(self.book.chapters) - 1))
            except Exception:
                chapter_index = 0

        self.load_chapter(chapter_index)

    def load_chapter(self, index: int) -> None:
        if not self.book.chapters:
            return
        if index < 0 or index >= len(self.book.chapters):
            return

        self.current_chapter_index = index
        chapter = self.book.chapters[index]

        self.chapter_list.blockSignals(True)
        self.chapter_list.setCurrentRow(index)
        self.chapter_list.blockSignals(False)

        self.reader_view.load(QUrl.fromLocalFile(str(chapter.file_path)))
        self._update_progress_label(index, 0)
        self.statusBar().showMessage(
            f"Chapter {index + 1} of {len(self.book.chapters)} — single-click a word for Dictionary lookup"
        )

    def install_word_click_handler(self, ok: bool) -> None:
        if not ok:
            return

        self.reader_view.page().runJavaScript(
            INSTALL_WORD_LOOKUP_JS,
            lambda _result: self.after_word_handler_installed(),
        )


    def after_word_handler_installed(self) -> None:
        self.apply_saved_word_highlights()
        self.apply_tashkeel_visibility()
        self.apply_dark_mode()
        self.apply_reader_font()

    def apply_saved_word_highlights(self) -> None:
        if not self.book.book_id:
            return
        words = self.vocab_store.saved_words_for_book(self.book.book_id)
        words_json = json.dumps(words, ensure_ascii=False)
        js = f"""
        (function() {{
            const words = {words_json};
            const norm = window.__arabicReaderNormalize || function(s) {{ return s || ''; }};
            window.__arabicReaderSavedWords = new Set(words.map(norm));
            document.querySelectorAll('.lookup-word').forEach(function(el) {{
                const n = norm(el.dataset.word || el.textContent || '');
                el.dataset.norm = n;
                if (window.__arabicReaderSavedWords.has(n)) {{
                    el.classList.add('lookup-word-saved');
                }} else {{
                    el.classList.remove('lookup-word-saved');
                }}
            }});
        }})();
        """
        self.reader_view.page().runJavaScript(js)

    def previous_chapter(self) -> None:
        self.load_chapter(self.current_chapter_index - 1)

    def next_chapter(self) -> None:
        self.load_chapter(self.current_chapter_index + 1)

    def zoom_in(self) -> None:
        self.zoom_factor = min(3.0, self.zoom_factor + 0.1)
        self.reader_view.setZoomFactor(self.zoom_factor)
        self.settings.setValue("zoom_factor", self.zoom_factor)

    def zoom_out(self) -> None:
        self.zoom_factor = max(0.5, self.zoom_factor - 0.1)
        self.reader_view.setZoomFactor(self.zoom_factor)
        self.settings.setValue("zoom_factor", self.zoom_factor)

    def reset_zoom(self) -> None:
        self.zoom_factor = 1.0
        self.reader_view.setZoomFactor(self.zoom_factor)
        self.settings.setValue("zoom_factor", self.zoom_factor)

    def find_next(self) -> None:
        text = self.find_box.text().strip()
        if text:
            self.reader_view.findText(text)

    def _lookup_mode_label(self) -> str:
        if getattr(self, "lookup_mode", "popup") == "dictionary_app":
            return "Lookup: Dictionary.app"
        return "Lookup: Popup"

    def toggle_lookup_mode(self) -> None:
        self.lookup_mode = "dictionary_app" if self.lookup_mode == "popup" else "popup"
        self.settings.setValue("lookup_mode", self.lookup_mode)
        self.lookup_mode_action.setText(self._lookup_mode_label())
        if self.lookup_mode == "dictionary_app":
            self.statusBar().showMessage("Lookup mode: opens macOS Dictionary.app with dict://word")
        else:
            self.statusBar().showMessage("Lookup mode: in-app popup")

    def _definition_mode_label(self) -> str:
        if getattr(self, "definition_mode", "dictionary") == "saved":
            return "Definition: Saved"
        return "Definition: Dictionary"

    def toggle_definition_mode(self) -> None:
        self.definition_mode = "saved" if self.definition_mode == "dictionary" else "dictionary"
        self.settings.setValue("definition_mode", self.definition_mode)
        self.definition_mode_action.setText(self._definition_mode_label())
        self.statusBar().showMessage(f"{self._definition_mode_label()} mode")
    
    def _tashkeel_label(self) -> str:
        return "Show Tashkeel" if self.hide_tashkeel else "Hide Tashkeel"


    def toggle_tashkeel(self) -> None:
        self.hide_tashkeel = not self.hide_tashkeel
        self.settings.setValue("hide_tashkeel", "true" if self.hide_tashkeel else "false")
        self.tashkeel_action.setText(self._tashkeel_label())
        self.apply_tashkeel_visibility()

        if self.hide_tashkeel:
            self.statusBar().showMessage("Tashkeel hidden")
        else:
            self.statusBar().showMessage("Tashkeel shown")


    def apply_tashkeel_visibility(self) -> None:
        js = TOGGLE_TASHKEEL_JS.replace(
            "__HIDDEN__",
            "true" if self.hide_tashkeel else "false"
        )
        self.reader_view.page().runJavaScript(js)

    def open_word_in_dictionary_app(self, word: str) -> None:
        word = clean_lookup_word(word)
        if not word:
            return
        os.system(f"open 'dict://{quote(word)}' >/dev/null 2>&1 &")

    def current_chapter_title(self) -> str:
        if 0 <= self.current_chapter_index < len(self.book.chapters):
            return self.book.chapters[self.current_chapter_index].title
        return ""

    def lookup_word(self, clicked_word: str) -> None:
        clicked_word = clean_lookup_word(clicked_word)
        if not clicked_word:
            return

        if self.lookup_mode == "dictionary_app":
            self.open_word_in_dictionary_app(clicked_word)
            return

        normalized_word = normalize_arabic(clicked_word)
        saved = self.vocab_store.get_saved_word(self.book.book_id, normalized_word)
        term_used, dictionary_definition = dictionary_lookup(clicked_word)

        show_saved = self.definition_mode == "saved" and saved is not None
        displayed_definition = saved.saved_definition if show_saved else dictionary_definition
        displayed_source = "Saved definition" if show_saved else "Dictionary"

        record = LookupRecord(
            clicked_word=clicked_word,
            normalized_word=normalized_word,
            term_used=term_used,
            dictionary_definition=dictionary_definition,
            book_id=self.book.book_id,
            book_title=self.book.title or (self.book.path.stem if self.book.path else ""),
            chapter=self.current_chapter_title(),
            chapter_index=self.current_chapter_index,
            saved=saved,
            displayed_definition=displayed_definition,
            displayed_source=displayed_source,
        )
        self.lookup_popup.show_lookup(record)

    def open_save_vocabulary_dialog(self, record_obj: object) -> None:
        if not isinstance(record_obj, LookupRecord):
            return
        record = record_obj

        # Refresh the saved state in case it changed since the popup opened.
        record.saved = self.vocab_store.get_saved_word(record.book_id, record.normalized_word)

        dialog = SaveVocabDialog(record, self)
        dialog.deletedRequested.connect(self.delete_vocabulary_record)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            saved_definition = dialog.saved_definition()
            if not dialog.saved_definition_plain_text():
                QMessageBox.warning(self, "Definition required", "Please enter a definition before saving.")
                return
            self.vocab_store.save_word(record, saved_definition=saved_definition, note=dialog.note())
            self.apply_saved_word_highlights()
            self.statusBar().showMessage(f"Saved '{record.clicked_word}' to vocabulary database")
            # QMessageBox.information(self, "Saved word", f"Saved '{record.clicked_word}'.")

    def delete_vocabulary_record(self, record_obj: object) -> None:
        if not isinstance(record_obj, LookupRecord):
            return
        self.vocab_store.delete_word(record_obj.book_id, record_obj.normalized_word)
        self.apply_saved_word_highlights()
        self.statusBar().showMessage(f"Deleted saved word '{record_obj.clicked_word}'")

    def export_vocab_csv(self) -> None:
        self.vocab_store.export_csv(VOCAB_CSV_PATH)
        os.system(f"open '{VOCAB_CSV_PATH}' >/dev/null 2>&1 &")
        self.statusBar().showMessage(f"Exported vocabulary CSV to {VOCAB_CSV_PATH}")

    def remove_active_highlight(self) -> None:
        js = """
        document.querySelectorAll('.lookup-word-active').forEach(function(el) {
            el.classList.remove('lookup-word-active');
        });
        """
        self.reader_view.page().runJavaScript(js)

    # ── Translate panel ───────────────────────────────────────────────────────

    def _toggle_translate_mode(self, checked: bool) -> None:
        self.translate_in_app = checked
        if not checked:
            self._translate_panel.setVisible(False)

    def _show_translate_panel(self) -> None:
        if not self._translate_panel.isVisible():
            self._translate_panel.setVisible(True)
            sizes = self._splitter.sizes()
            if sizes[2] == 0:
                total = sum(sizes)
                panel_width = min(420, total // 3)
                sizes[2] = panel_width
                sizes[1] = max(200, sizes[1] - panel_width)
                self._splitter.setSizes(sizes)

    def _handle_translate(self, text: str) -> None:
        url = QUrl(
            f"https://translate.google.com/?sl=ar&tl=en&text={quote(text)}&op=translate"
        )
        if self.translate_in_app:
            self._show_translate_panel()
            self._translate_panel.load_url(url)
        else:
            QDesktopServices.openUrl(url)

    # ── AI panel ──────────────────────────────────────────────────────────────

    def _toggle_ai_panel(self, checked: bool) -> None:
        self._ai_panel.setVisible(checked)
        if checked:
            sizes = self._splitter.sizes()
            if sizes[-1] == 0:
                total = sum(sizes)
                panel_width = min(380, total // 3)
                sizes[-1] = panel_width
                sizes[-2] = max(200, sizes[-2] - panel_width)
                self._splitter.setSizes(sizes)

    def _show_ai_panel(self) -> None:
        if not self._ai_panel.isVisible():
            self._ai_panel_action.setChecked(True)  # triggers _toggle_ai_panel

    def _handle_ai_action(self, action_id: str, text: str) -> None:
        self._show_ai_panel()
        self._ai_panel.run_action(action_id, text)

    def _handle_custom_ai(self, prompt_template: str, text: str) -> None:
        self._show_ai_panel()
        self._ai_panel.run_action("custom", text, custom_prompt=prompt_template)

    # ── Toolbar icon refresh ──────────────────────────────────────────────────

    def _refresh_toolbar_icons(self) -> None:
        """Re-render all toolbar SVG icons for the current light/dark appearance."""
        for action in self._toolbar.actions():
            name = action.objectName()
            if name:
                action.setIcon(svg_icon(name))
        if hasattr(self, "_search_icon_label"):
            self._search_icon_label.setPixmap(
                svg_icon("search", size=18).pixmap(QSize(18, 18))
            )

    # ── Progress indicator ────────────────────────────────────────────────────

    def _update_progress_label(self, chapter_index: int, pct: int) -> None:
        total = len(self.book.chapters)
        if total > 0 and chapter_index >= 0:
            self._progress_label.setText(f"Ch {chapter_index + 1} / {total}  ·  {pct}%")
        else:
            self._progress_label.setText("")

    def _on_scroll_changed(self) -> None:
        self.reader_page.runJavaScript(
            "(function(){"
            "  var h = document.body.scrollHeight - window.innerHeight;"
            "  return h > 10 ? Math.round(window.scrollY / h * 100) : 100;"
            "})()",
            self._apply_scroll_pct,
        )

    def _apply_scroll_pct(self, pct: object) -> None:
        if pct is not None and self.current_chapter_index >= 0:
            self._update_progress_label(self.current_chapter_index, int(pct))

    # ── Font picker ───────────────────────────────────────────────────────────

    def _current_font_option(self) -> FontOption:
        for opt in self._font_options:
            if opt.display_name == self.reader_font:
                return opt
        return self._font_options[0]

    def _on_font_changed(self, index: int) -> None:
        if 0 <= index < len(self._font_options):
            self.reader_font = self._font_options[index].display_name
            self.settings.setValue("reader_font", self.reader_font)
            self.apply_reader_font()

    def apply_reader_font(self) -> None:
        """Inject @font-face + font-family override into the current chapter."""
        import json as _json
        opt = self._current_font_option()

        if opt.file_path is not None:
            font_uri = opt.file_path.as_uri()
            face_css = (
                f'@font-face {{'

                f'  font-family: "{opt.css_family}";'

                f'  src: url("{font_uri}");'

                f'  font-weight: normal; font-style: normal;'

                f'}}'

            )
            family_css = f'"{opt.css_family}", serif'
        else:
            face_css = ""
            family_css = opt.css_family

        face_js   = _json.dumps(face_css)
        override  = _json.dumps(
            f"html, body, p, div, li, blockquote {{"
            f" font-family: {family_css} !important; }}"
        )
        js = f"""
        (function() {{
            let el;
            el = document.getElementById('kalima-font-face');
            if (el) el.remove();
            el = document.getElementById('kalima-font-override');
            if (el) el.remove();
            if ({face_js}) {{
                el = document.createElement('style');
                el.id = 'kalima-font-face';
                el.textContent = {face_js};
                document.head.appendChild(el);
            }}
            el = document.createElement('style');
            el.id = 'kalima-font-override';
            el.textContent = {override};
            document.head.appendChild(el);
        }})();
        """
        self.reader_view.page().runJavaScript(js)

    def set_toolbar_style(self, style: str, save: bool = True) -> None:
        self.toolbar_style = style
        if save:
            self.settings.setValue("toolbar_style", style)
        qt_style = {
            "icon":      Qt.ToolButtonStyle.ToolButtonIconOnly,
            "icon_text": Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
            "text":      Qt.ToolButtonStyle.ToolButtonTextOnly,
        }.get(style, Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._toolbar.setToolButtonStyle(qt_style)

    def _dark_mode_label(self) -> str:
        return "Light Mode" if getattr(self, "dark_mode", False) else "Dark Mode"

    def toggle_dark_mode(self) -> None:
        self.dark_mode = not self.dark_mode
        self.settings.setValue("dark_mode", "true" if self.dark_mode else "false")
        self.dark_mode_action.setText(self._dark_mode_label())
        self.apply_dark_mode()
        self.statusBar().showMessage("Dark mode on" if self.dark_mode else "Dark mode off")

    def apply_dark_mode(self) -> None:
        js = APPLY_DARK_MODE_JS.replace("__DARK__", "true" if self.dark_mode else "false")
        self.reader_view.page().runJavaScript(js)

    def open_vocab_browser(self) -> None:
        dlg = VocabBrowserDialog(self.vocab_store, self)
        dlg.exec()
        self.apply_saved_word_highlights()

    def _load_recent_files(self) -> list[str]:
        raw = self.settings.value("recent_files", "[]")
        try:
            return json.loads(str(raw))[:MAX_RECENT_FILES]
        except Exception:
            return []

    def _add_to_recent_files(self, path: str) -> None:
        files = [f for f in self._recent_files if f != path]
        files.insert(0, path)
        self._recent_files = files[:MAX_RECENT_FILES]
        self.settings.setValue("recent_files", json.dumps(self._recent_files))
        self._update_recent_files_menu()

    def _update_recent_files_menu(self) -> None:
        if not hasattr(self, "_recent_menu"):
            return
        self._recent_menu.clear()
        if not self._recent_files:
            no_recent = self._recent_menu.addAction("No recent files")
            no_recent.setEnabled(False)
            return
        for path in self._recent_files:
            action = self._recent_menu.addAction(Path(path).name)
            action.setToolTip(path)
            action.triggered.connect(lambda checked, p=path: self._open_recent_epub(p))

    def _open_recent_epub(self, path: str) -> None:
        if not Path(path).exists():
            QMessageBox.warning(self, "File not found", f"Could not find:\n{path}")
            self._recent_files = [f for f in self._recent_files if f != path]
            self.settings.setValue("recent_files", json.dumps(self._recent_files))
            self._update_recent_files_menu()
            return
        self.open_epub(path, restore_position=True)

    def _sync_chapter_from_path(self, local_path: str) -> None:
        path = Path(local_path)
        for idx, chapter in enumerate(self.book.chapters):
            if chapter.file_path == path:
                self.current_chapter_index = idx
                self.chapter_list.blockSignals(True)
                self.chapter_list.setCurrentRow(idx)
                self.chapter_list.blockSignals(False)
                self.statusBar().showMessage(f"Chapter {idx + 1} of {len(self.book.chapters)}")
                return


def main() -> int:
    global _PROMPT_ACTIONS
    _PROMPT_ACTIONS = load_prompts()

    app = QApplication(sys.argv)
    app.setOrganizationName(APP_ORG)
    app.setApplicationName(APP_NAME)

    window = MainWindow()
    window.show()

    if DCSCopyTextDefinition is None:
        QMessageBox.warning(
            window,
            "Dictionary Services unavailable",
            "The reader will open, but word lookup needs macOS PyObjC DictionaryServices.\n\n"
            "Install it with:\n"
            "pip install pyobjc-framework-DictionaryServices",
        )

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
