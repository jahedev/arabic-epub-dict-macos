"""
main_window — The top-level QMainWindow that wires everything together.

`MainWindow` owns:

* the EPUB model (`EpubBook`) and vocabulary store
* the chapter sidebar, reader view, translate panel, and AI panel,
  laid out left-to-right inside a 4-pane `QSplitter`
* the toolbar (open/navigation/zoom/font/tashkeel/find/lookup mode/
  dark mode/vocab browser/export) and menu bar
* persistent settings (QSettings) for zoom, dark mode, lookup mode, etc.
* the JavaScript bridge calls into the reader page (saved-word
  highlighting, tashkeel toggle, dark-mode toggle, font override).

Every signal from `ReaderView` and `LookupPopup` ultimately funnels here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from PyQt6.QtCore import QSize, Qt, QUrl, QSettings
from PyQt6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QToolBar,
)

from .arabic import (
    DCSCopyTextDefinition,
    clean_lookup_word,
    dictionary_lookup,
    normalize_arabic,
)
from .config import (
    APP_NAME,
    APP_ORG,
    APPLY_DARK_MODE_JS,
    INSTALL_WORD_LOOKUP_JS,
    MAX_RECENT_FILES,
    TOGGLE_TASHKEEL_JS,
    VOCAB_CSV_PATH,
    VOCAB_DB_PATH,
)
from .dialogs import LookupPopup, SaveVocabDialog, VocabBrowserDialog
from .epub_book import EpubBook
from .fonts import FontOption, load_font_options
from .icons import svg_icon
from .models import LookupRecord
from .panels import OllamaPanel, TranslatePanel
from .reader import ReaderPage, ReaderView
from .vocabulary import VocabularyStore


class MainWindow(QMainWindow):
    """The application's only top-level window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Kalima")
        self.resize(1200, 820)

        # ── Persistent state ─────────────────────────────────────────────────
        self.settings = QSettings(APP_ORG, APP_NAME)
        self.vocab_store = VocabularyStore(VOCAB_DB_PATH)
        self.book = EpubBook()
        self.current_chapter_index = -1

        # Reader prefs — stored as strings (QSettings native) and parsed here.
        self.zoom_factor = float(self.settings.value("zoom_factor", 1.0))
        self.lookup_mode = str(self.settings.value("lookup_mode", "popup"))           # popup | dictionary_app
        self.definition_mode = str(self.settings.value("definition_mode", "dictionary"))  # dictionary | saved
        self.hide_tashkeel = str(self.settings.value("hide_tashkeel", "false")) == "true"
        self.dark_mode = str(self.settings.value("dark_mode", "false")) == "true"
        self.toolbar_style = str(self.settings.value("toolbar_style", "icon"))
        self.translate_in_app = str(self.settings.value("translate_in_app", "false")) == "true"
        self._font_options: list[FontOption] = load_font_options()
        self.reader_font = str(self.settings.value("reader_font", "System Default"))
        self._recent_files: list[str] = self._load_recent_files()

        # ── Sidebar (chapter list) ───────────────────────────────────────────
        self.chapter_list = QListWidget()
        self.chapter_list.setMaximumWidth(320)
        self.chapter_list.currentRowChanged.connect(self.load_chapter)

        # ── Reader (custom page + view) ──────────────────────────────────────
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

        # ── Right-side panels (hidden by default) ────────────────────────────
        self._translate_panel = TranslatePanel()
        self._translate_panel.setVisible(False)

        self._ai_panel = OllamaPanel(self.settings)
        self._ai_panel.setVisible(False)

        # ── 4-pane splitter: chapter list | reader | translate | ai ──────────
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

        # ── Lookup popup + find box ──────────────────────────────────────────
        self.lookup_popup = LookupPopup(self)
        self.lookup_popup.saveRequested.connect(self.open_save_vocabulary_dialog)
        self.lookup_popup.closed.connect(self.remove_active_highlight)

        self.find_box = QLineEdit()
        self.find_box.setPlaceholderText("Find in chapter…")
        self.find_box.returnPressed.connect(self.find_next)

        # ── Toolbar, menu, status bar ────────────────────────────────────────
        self._build_toolbar()
        self._build_menu_bar()
        self.setStatusBar(QStatusBar())
        self._progress_label = QLabel()
        self._progress_label.setStyleSheet("padding-right: 8px; color: gray;")
        self.statusBar().addPermanentWidget(self._progress_label)
        self.reader_page.scrollPositionChanged.connect(self._on_scroll_changed)

        # Recolor toolbar icons when macOS switches between light and dark mode.
        QApplication.instance().paletteChanged.connect(self._refresh_toolbar_icons)

        # ── Auto-open the last book ──────────────────────────────────────────
        last_path = self.settings.value("last_epub_path", "")
        if last_path and Path(str(last_path)).exists():
            try:
                self.open_epub(str(last_path), restore_position=True)
            except Exception:  # noqa: BLE001 — corrupt EPUB, swallow on startup
                pass

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def closeEvent(self, event):  # noqa: N802, ANN001 — Qt method
        """Persist reader prefs and remember the open book for next launch."""
        self.settings.setValue("zoom_factor", self.zoom_factor)
        self.settings.setValue("definition_mode", self.definition_mode)
        self.settings.setValue("dark_mode", "true" if self.dark_mode else "false")
        self.settings.setValue("toolbar_style", self.toolbar_style)
        self.settings.setValue("reader_font", self.reader_font)
        self.settings.setValue(
            "translate_in_app", "true" if self.translate_in_app else "false",
        )
        if self.book.path:
            self.settings.setValue("last_epub_path", str(self.book.path))
            self.settings.setValue(
                f"last_chapter::{self.book.path}", self.current_chapter_index,
            )
        self.book.close()
        super().closeEvent(event)

    # ── Toolbar / menu construction ──────────────────────────────────────────

    def _build_toolbar(self) -> None:
        self._toolbar = QToolBar("Main")
        toolbar = self._toolbar  # local alias for brevity
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)

        # Helper: create an action with an icon, and tag its object name so
        # `_refresh_toolbar_icons` can rerender it when the OS theme changes.
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

        # Font dropdown
        self.font_combo = QComboBox()
        self.font_combo.setMaximumWidth(170)
        self.font_combo.setToolTip("Reader font")
        for opt in self._font_options:
            self.font_combo.addItem(opt.display_name)
        current_idx = next(
            (i for i, o in enumerate(self._font_options) if o.display_name == self.reader_font),
            0,
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

        # Search box + find-next
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
            "True macOS Force Click popover is not reliably exposed through "
            "PyQt WebEngine, so Dictionary.app mode uses dict://word."
        )
        self.lookup_mode_action.triggered.connect(self.toggle_lookup_mode)
        toolbar.addAction(self.lookup_mode_action)

        self.definition_mode_action = _ia("definition-saved", self._definition_mode_label())
        self.definition_mode_action.setToolTip(
            "When a word is already saved, choose whether clicking it shows "
            "your saved definition or a fresh dictionary lookup."
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

        # Apply the persisted icon/text style choice.
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

        self._translate_in_app_action = view_menu.addAction(
            "Google Translate: Open in App Panel"
        )
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

    # ── File open / chapter navigation ───────────────────────────────────────

    def choose_epub(self) -> None:
        """Open-file dialog that remembers the last folder used."""
        last_dir = str(self.settings.value("last_open_dir", str(Path.home())))
        path, _ = QFileDialog.getOpenFileName(
            self, "Open EPUB", last_dir,
            "EPUB files (*.epub);;All files (*)",
        )
        if path:
            self.settings.setValue("last_open_dir", str(Path(path).parent))
            self.open_epub(path, restore_position=False)

    def open_epub(self, path: str, restore_position: bool = False) -> None:
        """Load ``path``, populate the chapter list, jump to chapter 0 (or saved)."""
        try:
            self.book.open(path)
        except Exception as exc:  # noqa: BLE001 — show the parse error
            QMessageBox.critical(self, "Could not open EPUB", str(exc))
            return

        # Register the book in the DB so its FK constraint will satisfy later inserts.
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
            except Exception:  # noqa: BLE001
                chapter_index = 0

        self.load_chapter(chapter_index)

    def load_chapter(self, index: int) -> None:
        if not self.book.chapters:
            return
        if index < 0 or index >= len(self.book.chapters):
            return

        self.current_chapter_index = index
        chapter = self.book.chapters[index]

        # Keep the sidebar selection in sync without re-firing the signal.
        self.chapter_list.blockSignals(True)
        self.chapter_list.setCurrentRow(index)
        self.chapter_list.blockSignals(False)

        self.reader_view.load(QUrl.fromLocalFile(str(chapter.file_path)))
        self._update_progress_label(index, 0)
        self.statusBar().showMessage(
            f"Chapter {index + 1} of {len(self.book.chapters)} — "
            f"single-click a word for Dictionary lookup"
        )

    def previous_chapter(self) -> None:
        self.load_chapter(self.current_chapter_index - 1)

    def next_chapter(self) -> None:
        self.load_chapter(self.current_chapter_index + 1)

    def _sync_chapter_from_path(self, local_path: str) -> None:
        """Update the chapter sidebar after a WebEngine in-book navigation."""
        path = Path(local_path)
        for idx, chapter in enumerate(self.book.chapters):
            if chapter.file_path == path:
                self.current_chapter_index = idx
                self.chapter_list.blockSignals(True)
                self.chapter_list.setCurrentRow(idx)
                self.chapter_list.blockSignals(False)
                self.statusBar().showMessage(
                    f"Chapter {idx + 1} of {len(self.book.chapters)}"
                )
                return

    # ── Word-lookup orchestration ────────────────────────────────────────────

    def install_word_click_handler(self, ok: bool) -> None:
        """After each chapter loads, wrap every word and install click handlers."""
        if not ok:
            return
        self.reader_view.page().runJavaScript(
            INSTALL_WORD_LOOKUP_JS,
            lambda _result: self.after_word_handler_installed(),
        )

    def after_word_handler_installed(self) -> None:
        """Re-apply per-chapter highlights and view settings after JS installs."""
        self.apply_saved_word_highlights()
        self.apply_tashkeel_visibility()
        self.apply_dark_mode()
        self.apply_reader_font()

    def apply_saved_word_highlights(self) -> None:
        """Tell the page which normalized words are saved so it can highlight."""
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

    def open_word_in_dictionary_app(self, word: str) -> None:
        """Hand off to the system Dictionary.app via the dict:// URL scheme."""
        word = clean_lookup_word(word)
        if not word:
            return
        os.system(f"open 'dict://{quote(word)}' >/dev/null 2>&1 &")

    def current_chapter_title(self) -> str:
        if 0 <= self.current_chapter_index < len(self.book.chapters):
            return self.book.chapters[self.current_chapter_index].title
        return ""

    def lookup_word(self, clicked_word: str) -> None:
        """Main entry point for every word the user clicks/double-clicks."""
        clicked_word = clean_lookup_word(clicked_word)
        if not clicked_word:
            return

        # Mode 1: just open Dictionary.app
        if self.lookup_mode == "dictionary_app":
            self.open_word_in_dictionary_app(clicked_word)
            return

        # Mode 2: in-app popup
        normalized_word = normalize_arabic(clicked_word)
        saved = self.vocab_store.get_saved_word(self.book.book_id, normalized_word)
        term_used, dictionary_definition = dictionary_lookup(clicked_word)

        # When in "saved" definition mode and the word is already saved, show
        # the user's saved definition instead of querying the dictionary.
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
        """Show the save dialog. Connected to LookupPopup.saveRequested."""
        if not isinstance(record_obj, LookupRecord):
            return
        record = record_obj

        # Re-check the DB in case state changed while the popup was open.
        record.saved = self.vocab_store.get_saved_word(
            record.book_id, record.normalized_word,
        )

        dialog = SaveVocabDialog(record, self)
        dialog.deletedRequested.connect(self.delete_vocabulary_record)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            saved_definition = dialog.saved_definition()
            if not dialog.saved_definition_plain_text():
                QMessageBox.warning(
                    self, "Definition required",
                    "Please enter a definition before saving.",
                )
                return
            self.vocab_store.save_word(
                record, saved_definition=saved_definition, note=dialog.note(),
            )
            self.apply_saved_word_highlights()
            self.statusBar().showMessage(
                f"Saved '{record.clicked_word}' to vocabulary database"
            )

    def delete_vocabulary_record(self, record_obj: object) -> None:
        if not isinstance(record_obj, LookupRecord):
            return
        self.vocab_store.delete_word(record_obj.book_id, record_obj.normalized_word)
        self.apply_saved_word_highlights()
        self.statusBar().showMessage(f"Deleted saved word '{record_obj.clicked_word}'")

    def remove_active_highlight(self) -> None:
        """Clear the orange "active" highlight when the popup closes."""
        js = """
        document.querySelectorAll('.lookup-word-active').forEach(function(el) {
            el.classList.remove('lookup-word-active');
        });
        """
        self.reader_view.page().runJavaScript(js)

    # ── CSV export and Vocab browser ─────────────────────────────────────────

    def export_vocab_csv(self) -> None:
        self.vocab_store.export_csv(VOCAB_CSV_PATH)
        os.system(f"open '{VOCAB_CSV_PATH}' >/dev/null 2>&1 &")
        self.statusBar().showMessage(f"Exported vocabulary CSV to {VOCAB_CSV_PATH}")

    def open_vocab_browser(self) -> None:
        dlg = VocabBrowserDialog(self.vocab_store, self)
        dlg.exec()
        # The browser may have edited/deleted entries — refresh highlights.
        self.apply_saved_word_highlights()

    # ── Zoom / find ──────────────────────────────────────────────────────────

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

    # ── Toggles: lookup mode / definition mode / tashkeel / dark mode ────────

    def _lookup_mode_label(self) -> str:
        if getattr(self, "lookup_mode", "popup") == "dictionary_app":
            return "Lookup: Dictionary.app"
        return "Lookup: Popup"

    def toggle_lookup_mode(self) -> None:
        self.lookup_mode = "dictionary_app" if self.lookup_mode == "popup" else "popup"
        self.settings.setValue("lookup_mode", self.lookup_mode)
        self.lookup_mode_action.setText(self._lookup_mode_label())
        if self.lookup_mode == "dictionary_app":
            self.statusBar().showMessage(
                "Lookup mode: opens macOS Dictionary.app with dict://word"
            )
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
        self.statusBar().showMessage(
            "Tashkeel hidden" if self.hide_tashkeel else "Tashkeel shown"
        )

    def apply_tashkeel_visibility(self) -> None:
        js = TOGGLE_TASHKEEL_JS.replace(
            "__HIDDEN__", "true" if self.hide_tashkeel else "false",
        )
        self.reader_view.page().runJavaScript(js)

    def _dark_mode_label(self) -> str:
        return "Light Mode" if getattr(self, "dark_mode", False) else "Dark Mode"

    def toggle_dark_mode(self) -> None:
        self.dark_mode = not self.dark_mode
        self.settings.setValue("dark_mode", "true" if self.dark_mode else "false")
        self.dark_mode_action.setText(self._dark_mode_label())
        self.apply_dark_mode()
        self.statusBar().showMessage(
            "Dark mode on" if self.dark_mode else "Dark mode off"
        )

    def apply_dark_mode(self) -> None:
        js = APPLY_DARK_MODE_JS.replace("__DARK__", "true" if self.dark_mode else "false")
        self.reader_view.page().runJavaScript(js)

    # ── Translate panel ──────────────────────────────────────────────────────

    def _toggle_translate_mode(self, checked: bool) -> None:
        self.translate_in_app = checked
        if not checked:
            self._translate_panel.setVisible(False)

    def _show_translate_panel(self) -> None:
        """Show the translate panel and give it some screen real estate."""
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
        """Route a "Translate on Google" request to browser or in-app panel."""
        url = QUrl(
            f"https://translate.google.com/?sl=ar&tl=en&text={quote(text)}&op=translate"
        )
        if self.translate_in_app:
            self._show_translate_panel()
            self._translate_panel.load_url(url)
        else:
            QDesktopServices.openUrl(url)

    # ── AI panel ─────────────────────────────────────────────────────────────

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
        """Force the AI panel visible (via the menu action so state stays in sync)."""
        if not self._ai_panel.isVisible():
            self._ai_panel_action.setChecked(True)  # triggers _toggle_ai_panel

    def _handle_ai_action(self, action_id: str, text: str) -> None:
        self._show_ai_panel()
        self._ai_panel.run_action(action_id, text)

    def _handle_custom_ai(self, prompt_template: str, text: str) -> None:
        self._show_ai_panel()
        self._ai_panel.run_action("custom", text, custom_prompt=prompt_template)

    # ── Toolbar appearance refresh ───────────────────────────────────────────

    def _refresh_toolbar_icons(self) -> None:
        """Re-render every toolbar SVG icon for the current light/dark palette."""
        for action in self._toolbar.actions():
            name = action.objectName()
            if name:
                action.setIcon(svg_icon(name))
        if hasattr(self, "_search_icon_label"):
            self._search_icon_label.setPixmap(
                svg_icon("search", size=18).pixmap(QSize(18, 18))
            )

    # ── Reading-progress indicator (status bar) ──────────────────────────────

    def _update_progress_label(self, chapter_index: int, pct: int) -> None:
        total = len(self.book.chapters)
        if total > 0 and chapter_index >= 0:
            self._progress_label.setText(f"Ch {chapter_index + 1} / {total}  ·  {pct}%")
        else:
            self._progress_label.setText("")

    def _on_scroll_changed(self) -> None:
        """Compute and display scroll percent for the current chapter."""
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

    # ── Reader font picker ───────────────────────────────────────────────────

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

        # json.dumps lets us safely embed CSS strings into the JS literal.
        face_js = json.dumps(face_css)
        override = json.dumps(
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

    # ── Toolbar style (icon / icon+text / text) ──────────────────────────────

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

    # ── Recent files menu ────────────────────────────────────────────────────

    def _load_recent_files(self) -> list[str]:
        raw = self.settings.value("recent_files", "[]")
        try:
            return json.loads(str(raw))[:MAX_RECENT_FILES]
        except Exception:  # noqa: BLE001
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


# Tiny convenience export so callers can do:
#   from kalima_app.main_window import DCSCopyTextDefinition
# without reaching into kalima_app.arabic just to test for None.
__all__ = ["MainWindow", "DCSCopyTextDefinition"]
