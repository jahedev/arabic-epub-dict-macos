"""
Kalima — Arabic EPUB reader for macOS.

This package contains the modular implementation. The top-level `kalima.py`
script imports `main()` from `kalima_app.main` and runs the GUI app.

Module layout
-------------
    config        — Constants, paths, CSS, JavaScript snippets, model presets
    icons         — SVG icon factory (auto light/dark)
    fonts         — Bundled reader font discovery
    models        — Dataclasses: Chapter, SavedVocab, LookupRecord
    utils         — Small helpers (timestamps, file hashing, safe paths)
    arabic        — Word normalization, Dictionary Services lookup, HTML formatters
    epub_book     — EPUB extraction (EpubBook) + ebooklib safety patch
    vocabulary    — SQLite vocabulary store (VocabularyStore)
    anki          — `.apkg` export via genanki
    ollama        — Local AI client + background workers + prompt registry
    reader        — QWebEngineView subclass used to display chapters
    panels        — TranslatePanel, OllamaPanel, OllamaSetupDialog, ModelManagerDialog
    dialogs       — SaveVocabDialog, AnkiExportDialog, VocabBrowserDialog, LookupPopup
    main_window   — MainWindow (top-level glue)
    main          — Entry point used by `kalima.py`
"""

__version__ = "0.2.0"
