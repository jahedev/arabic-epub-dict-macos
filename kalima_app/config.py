"""
config — Compile-time constants and asset paths.

Everything here is data: paths, regexes, embedded CSS, embedded JavaScript,
Ollama defaults, recommended models. No Qt or app imports — this module is
safe for every other module to import from.

Notes
-----
* `BASE_DIR` resolves correctly both when running from source and inside a
  PyInstaller .app bundle. The non-frozen branch points to the **repository
  root** (one level above this file), so `BASE_DIR / "assets"` always lands
  on the asset folder.
* All the `*_JS` strings contain placeholders like `__X__` / `__HIDDEN__` /
  `__DARK__`. Callers do a plain `.replace()` before sending them to the
  reader's WebEngine page.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


# ── App identity ──────────────────────────────────────────────────────────────
APP_ORG = "Kalima"
APP_NAME = "Kalima"

# Where user-specific data (SQLite DB, etc.) lives.
APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
VOCAB_DB_PATH = APP_SUPPORT_DIR / "vocabulary.sqlite3"
VOCAB_CSV_PATH = Path.home() / "Documents" / "kalima_vocab.csv"


# ── Asset paths (work in source and frozen builds) ────────────────────────────
if getattr(sys, "frozen", False):
    # PyInstaller drops the bundled assets next to the binary at sys._MEIPASS.
    BASE_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    # When running from source this file lives in kalima_app/, so go up once.
    BASE_DIR = Path(__file__).resolve().parent.parent

ICONS_DIR = BASE_DIR / "assets" / "icons"
FONTS_DIR = BASE_DIR / "assets" / "fonts"
PROMPTS_PATH = BASE_DIR / "assets" / "prompts.json"


# ── Misc UI constants ─────────────────────────────────────────────────────────
MAX_RECENT_FILES = 10


# ── Arabic text normalization ─────────────────────────────────────────────────
# Combining tashkeel / diacritics blocks we strip when normalizing words.
ARABIC_DIACRITICS_RE = re.compile(
    r"[ؐ-ًؚ-ٰٟۖ-ۭ]"
)

# Characters trimmed from the edges of a clicked word. Includes bidi control
# marks, common Arabic and Latin punctuation, and tatweel-adjacent symbols.
TRIM_CHARS = (
    "﻿‎‏‪‫‬‭‮⁦⁧⁨⁩"
    "\t\r\n .,;:!?()[]{}<>\"'“”‘’،؛؟«»…ـ"
)


# ── Reader stylesheet ─────────────────────────────────────────────────────────
# Injected into every EPUB chapter before display. Defines RTL layout,
# saved-word highlighting, dark mode, selection colors, and responsive
# padding for narrow panes.
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


# ── JavaScript snippets injected into the reader ──────────────────────────────
# WORD_AT_POINT_JS asks the page what word is under (x, y). Used by single-
# click handling: when the cursor lands inside a `.lookup-word` span, we grab
# `data-word` and emit it back to Python via the lookup:// URL scheme.
WORD_AT_POINT_JS = r"""
(function() {
    const x = __X__;
    const y = __Y__;

    function clean(s) {
        if (!s) return "";
        return s
            .replace(/[‎‏‪-‮⁦-⁩﻿]/g, "")
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

# INSTALL_WORD_LOOKUP_JS walks the DOM once and wraps every word-like run of
# characters in a <span class="lookup-word" data-word="…"> so we can hover,
# style, and click them. Re-entry is guarded by `__arabicReaderLookupInstalled`.
# Saved words are tagged via the `__arabicReaderSavedWords` Set populated by
# MainWindow.apply_saved_word_highlights().
INSTALL_WORD_LOOKUP_JS = r"""
(function() {
    if (window.__arabicReaderLookupInstalled) return "already-installed";
    window.__arabicReaderLookupInstalled = true;

    const wordRe = /([؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿A-Za-zÀ-ÖØ-öø-ÿ0-9’'\-]+)/g;
    const skipTags = new Set(["SCRIPT", "STYLE", "TEXTAREA", "INPUT", "SELECT", "OPTION", "CODE", "PRE"]);

    function clean(s) {
        if (!s) return "";
        return s
            .replace(/[‎‏‪-‮⁦-⁩﻿]/g, "")
            .replace(/^[\s.,;:!?()\[\]{}<>"'“”‘’،؛؟«»…ـ]+/g, "")
            .replace(/[\s.,;:!?()\[\]{}<>"'“”‘’،؛؟«»…ـ]+$/g, "")
            .replace(/\s+/g, " ")
            .trim();
    }

    function normalizeArabic(s) {
        return clean(s)
            .replace(/[ؐ-ًؚ-ٰٟۖ-ۭ]/g, "")
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

# TOGGLE_TASHKEEL_JS toggles whether Arabic diacritics show. We stash the
# original textContent on each span the first time so toggling is lossless.
TOGGLE_TASHKEEL_JS = r"""
(function(hidden) {
    function stripTashkeel(s) {
        return (s || "")
            .replace(/[ؐ-ًؚ-ٰٟۖ-ۭ]/g, "");
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

# APPLY_DARK_MODE_JS toggles the `reader-dark` class on <html>. The reader
# stylesheet keys all dark-mode overrides off that class.
APPLY_DARK_MODE_JS = r"""
(function(dark) {
    document.documentElement.classList.toggle('reader-dark', dark);
})(__DARK__);
"""


# ── Ollama integration ────────────────────────────────────────────────────────
OLLAMA_BASE_URL = "http://localhost:11434"

# Curated list shown in the Ollama setup and Model Manager dialogs. Ordered
# best → smallest. The `id` must match what `ollama pull` accepts.
RECOMMENDED_MODELS: list[dict] = [
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


# ── Anki ──────────────────────────────────────────────────────────────────────
# Permanent model ID. Changing this number would orphan every existing card
# already imported into users' Anki collections.
ANKI_MODEL_ID = 1700000001
