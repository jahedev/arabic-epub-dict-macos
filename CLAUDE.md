# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Kalima is

macOS-only PyQt6 desktop app: an Arabic EPUB reader with click-to-lookup against
the macOS Dictionary Services API, a local SQLite vocabulary store, Anki `.apkg`
export via `genanki`, and a right-side AI sidebar that streams from a local
[Ollama](https://ollama.com) server. Not cross-platform — Dictionary lookup
relies on PyObjC `DictionaryServices`.

## Common commands

Run from source (uses `.venv/`):
```bash
source .venv/bin/activate
python kalima.py
```

Build the `.app` and `.dmg` locally:
```bash
./build.sh                     # current arch, .app + DMG
./build.sh --app-only          # skip DMG
./build.sh --arm64             # Apple Silicon only
./build.sh --intel             # Intel only (uses .venv-intel + arch -x86_64)
./build.sh --both              # both architectures
./build.sh --version v1.2.0    # sets version suffix in DMG filename
```

Under the hood: `build.sh` shells `pyinstaller kalima.spec --noconfirm`, then
`hdiutil` for the DMG. Intel builds on Apple Silicon require a separate
`.venv-intel` created under `arch -x86_64` with Intel Homebrew's Python at
`/usr/local/bin/python3.12`. Release builds are produced by
`.github/workflows/build.yml` on any `v*` tag.

There is no test suite and no linter configured.

## Architecture — the important cross-file wiring

The codebase was refactored from a 3,000-line monolith into a `kalima_app/`
package. `kalima.py` at the repo root is a **25-line entry-point shim** that
exists because PyInstaller (`kalima.spec`) expects a stable file to anchor on.
All real code lives in `kalima_app/` — see its `__init__.py` for the module
map.

**Import layering (respect this — cycles will bite):**
```
config ── icons ── (Qt widgets)
   │        └── fonts
   ├── models ── vocabulary ── anki
   │        └── arabic
   └── ollama ── reader ─┐
                          ├── panels
                          ├── dialogs
                          └── main_window ── main
```

`config.py` is data-only (no Qt, no ebooklib). Every other module can import
from it freely.

**Prompt registry pattern.** `ollama.PROMPT_ACTIONS` is a module-level list
that `main.py` populates once at startup by calling `ollama.load_prompts()`
(reads `assets/prompts.json`). `reader.py` reads this list live when building
the right-click "Ask AI…" submenu. If you add a new call site, use
`from . import ollama` then `ollama.PROMPT_ACTIONS` — don't do
`from .ollama import PROMPT_ACTIONS` (that captures a stale reference).

**JS bridges into the WebEngine reader.** All embedded JavaScript lives in
`config.py` as `WORD_AT_POINT_JS`, `INSTALL_WORD_LOOKUP_JS`,
`TOGGLE_TASHKEEL_JS`, `APPLY_DARK_MODE_JS`. Callers do a plain `.replace()`
on placeholders like `__X__`, `__HIDDEN__`, `__DARK__` before sending them to
`page().runJavaScript()`. `INSTALL_WORD_LOOKUP_JS` wraps every text run in a
`<span class="lookup-word" data-word="…">`; clicks are surfaced back to
Python via a custom `lookup://word?value=…` URL scheme intercepted in
`reader.ReaderPage.acceptNavigationRequest`.

**Vocabulary keying.** SQLite uniqueness is `(book_id, normalized_word)`.
`book_id` is the SHA-256 of the EPUB file (`utils.calculate_file_hash`), not
the file path — the same book saved under different names shares vocabulary.
`normalized_word` strips diacritics, tatweel, and unifies alef/ya variants
(`arabic.normalize_arabic`). `PRAGMA foreign_keys = ON` runs on every
connection — without it SQLite silently ignores the FK.

**Anki export stability.** `anki.build_anki_package` uses
`genanki.guid_for(book_id, normalized_word)` for deterministic GUIDs, so
re-exporting updates existing Anki notes instead of duplicating. The model
ID `ANKI_MODEL_ID = 1700000001` in `config.py` is **permanent** — changing
it would orphan every existing user's Anki cards. Deck IDs use
`zlib.crc32(deck_name)` (not Python `hash()`, which is randomized per run).

**Ollama binary lookup.** Frozen `.app` bundles don't inherit the shell PATH,
so `ollama.find_binary()` falls back to `/opt/homebrew/bin/ollama` (Apple
Silicon) and `/usr/local/bin/ollama` (Intel) after `shutil.which` fails.
When adding any new external-binary call, follow the same pattern.

**Asset paths in frozen builds.** `config.BASE_DIR` resolves to
`sys._MEIPASS` when frozen, otherwise to the repo root (one level above
`kalima_app/`). Never use `Path(__file__).parent` directly for asset lookups
— always go through `BASE_DIR`.

**ebooklib safety patch.** `epub_book.py` monkey-patches
`epub.EpubReader.read_file` at import time to return `b""` instead of
raising `KeyError` on missing manifest entries — this is a workaround for
long-standing ebooklib issues (#161, #197, #222, #281). The patch runs when
the module is first imported; don't remove it.

**Qt right-click quirk.** PyQt6's `QContextMenuEvent` does not expose
`globalPosition().toPoint()` reliably — use `event.globalPos()` (see
`reader.ReaderView.contextMenuEvent`).

## Adding features

- **New AI action**: append to `assets/prompts.json`. No code changes needed
  — the right-click menu and `OllamaPanel.run_action` both read from
  `ollama.PROMPT_ACTIONS`.
- **New toolbar button**: add to `main_window.MainWindow._build_toolbar`
  using the `_ia(icon_name, text)` helper. The icon's SVG must live in
  `assets/icons/<name>.svg` using `currentColor`; `_refresh_toolbar_icons`
  auto-recolors it on light/dark switches.
- **New settings key**: read via `self.settings.value(key, default)` in
  `MainWindow.__init__`, write in `closeEvent`. Values are stored as
  strings by `QSettings` — bool needs explicit `"true"/"false"` conversion.

## Notes

`kalima_legacy.py.bak` at the repo root is the pre-refactor 3,000-line
monolith kept as a safety backup. Nothing imports it; delete it once the
modular version is fully trusted. `notes/` holds miscellaneous design
scratch that is not part of the build.
