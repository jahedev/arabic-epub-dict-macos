"""
dialogs — Modal dialogs for vocabulary and word lookup.

* `LookupPopup`        — non-modal popup that shows a single lookup result.
* `SaveVocabDialog`    — full-screen editor for saving / editing one word.
* `VocabBrowserDialog` — searchable browser over the whole vocab database.
* `AnkiExportDialog`   — scope + destination picker for .apkg export.

Each dialog is intentionally self-contained. They use Qt signals to talk
back to the main window where needed (e.g. `LookupPopup.saveRequested`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import anki
from .arabic import (
    definition_text_to_editable_text,
    format_lookup_html,
    saved_definition_to_plain_text,
)
from .models import LookupRecord, SavedVocab
from .vocabulary import VocabularyStore


# ── Lookup popup ──────────────────────────────────────────────────────────────

class LookupPopup(QFrame):
    """Non-modal popup window showing one dictionary lookup result."""

    saveRequested = pyqtSignal(object)  # emits the underlying LookupRecord
    closed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        # Sized for a one-screen lookup; long entries scroll.
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
        """Render ``record`` and position the popup near the mouse cursor."""
        self._current_record = record
        clicked_word = record.clicked_word
        term_used = record.term_used
        self._current_word = term_used or clicked_word

        # The button label tells the user whether this is a new entry.
        self.save_btn.setText("Edit saved word" if record.saved else "Save word")

        if term_used and term_used != clicked_word:
            self.title.setText(f"{clicked_word}  →  {term_used}")
        else:
            self.title.setText(clicked_word)

        self.definition.setHtml(format_lookup_html(record))
        self.resize(820, 620)
        self.adjustSize()

        # Position near the cursor but clamp to the current screen.
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
        """Hand off the current word to the system Dictionary.app via dict://."""
        if not self._current_word:
            return
        os.system(f"open 'dict://{quote(self._current_word)}' >/dev/null 2>&1 &")

    def hideEvent(self, event):  # noqa: N802, ANN001 — Qt method
        self.closed.emit()
        super().hideEvent(event)


# ── Save / edit dialog ────────────────────────────────────────────────────────

class SaveVocabDialog(QDialog):
    """Editor for the saved definition and optional note for one word."""

    deletedRequested = pyqtSignal(object)  # emits the underlying LookupRecord

    def __init__(self, record: LookupRecord, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.record = record
        self.setWindowTitle("Save vocabulary word")
        self.resize(720, 560)

        # ── Header
        word_label = QLabel(record.clicked_word)
        word_label.setStyleSheet("font-size: 28px; font-weight: 800;")
        word_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        meta = QLabel(f"Book: {record.book_title}\nChapter: {record.chapter}")
        meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        # ── Definition editor (RTL, plain text only)
        self.definition_edit = QTextEdit()
        self.definition_edit.setAcceptRichText(False)
        self.definition_edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.definition_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.definition_edit.setPlaceholderText("Edit the definition before saving…")
        self.definition_edit.setStyleSheet("font-size: 17px; line-height: 1.35;")

        # Pre-fill: prefer the user's saved definition (cleaned), fall back to
        # the dictionary result formatted for editing.
        initial_definition = (
            record.saved.saved_definition if record.saved else record.dictionary_definition
        )
        if record.saved:
            self.definition_edit.setPlainText(
                saved_definition_to_plain_text(initial_definition or "")
            )
        else:
            self.definition_edit.setPlainText(
                definition_text_to_editable_text(initial_definition or "")
            )

        # ── Note editor
        self.note_edit = QTextEdit()
        self.note_edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.note_edit.setMaximumHeight(110)
        self.note_edit.setPlaceholderText(
            "Optional note, memory aid, grammar note, example, etc."
        )
        self.note_edit.setPlainText(record.saved.note if record.saved else "")

        # ── Buttons
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
        layout.addWidget(QLabel(
            "Saved definition — edit, delete, or add anything before saving. "
            "Line breaks are kept."
        ))
        layout.addWidget(self.definition_edit)
        layout.addWidget(QLabel("Optional note"))
        layout.addWidget(self.note_edit)
        layout.addLayout(button_row)

    def saved_definition(self) -> str:
        """Clean editable text — the popup re-formats this on display."""
        return self.definition_edit.toPlainText().strip()

    def saved_definition_plain_text(self) -> str:
        """Alias used by the validation logic in MainWindow.open_save_…()."""
        return self.definition_edit.toPlainText().strip()

    def note(self) -> str:
        return self.note_edit.toPlainText().strip()

    def _delete_clicked(self) -> None:
        """Delete immediately (no confirmation) and close as rejected."""
        if self.record.saved is None:
            return
        self.deletedRequested.emit(self.record)
        self.reject()


# ── Anki export dialog ────────────────────────────────────────────────────────

class AnkiExportDialog(QDialog):
    """Scope + destination picker for Anki .apkg export."""

    def __init__(
        self,
        vocab_store: VocabularyStore,
        current_book_id: str,
        current_book_title: str,
        parent: Optional[QWidget] = None,
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

        # ── Scope
        scope_box = QFrame()
        scope_box.setFrameShape(QFrame.Shape.StyledPanel)
        sb = QVBoxLayout(scope_box)

        self._rb_current = None
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

        # ── Destination
        dest_row = QHBoxLayout()
        self._dest_edit = QLineEdit()
        default_name = (
            f"Kalima - {current_book_title}.apkg" if current_book_id else "Kalima.apkg"
        )
        self._dest_edit.setText(str(Path.home() / "Desktop" / default_name))
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)
        dest_row.addWidget(self._dest_edit, 1)
        dest_row.addWidget(browse_btn)
        layout.addWidget(QLabel("Save as:"))
        layout.addLayout(dest_row)

        # Auto-rename the destination when the scope changes.
        self._scope_group.idToggled.connect(self._update_filename)

        # ── Buttons
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
            count = anki.build_anki_package(records, output)
            QMessageBox.information(
                self,
                "Export complete",
                f"Exported {count} card{'s' if count != 1 else ''} to:\n{output}\n\n"
                "Double-click the file in Finder to import into Anki.\n"
                "Re-importing will update existing cards automatically.",
            )
            self.accept()
        except Exception as exc:  # noqa: BLE001 — relay to user
            QMessageBox.critical(self, "Export failed", str(exc))


# ── Vocab browser ─────────────────────────────────────────────────────────────

class VocabBrowserDialog(QDialog):
    """Searchable list of every saved vocab word, with edit/delete/export."""

    def __init__(
        self,
        vocab_store: VocabularyStore,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.vocab_store = vocab_store
        self.setWindowTitle("Vocabulary Browser")
        self.resize(860, 560)

        self._entries: list[SavedVocab] = []

        # ── Left pane: search + list
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter by word, definition, or note…")
        self.search_box.textChanged.connect(self._refresh)

        self.count_label = QLabel()

        self.word_list = QListWidget()
        self.word_list.itemSelectionChanged.connect(self._on_selection)
        self.word_list.itemDoubleClicked.connect(self._edit_selected)

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

        # ── Right pane: detail view
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

        # ── Wire panes
        splitter = QSplitter()
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(splitter)

        self._refresh()

    # ── List management ──────────────────────────────────────────────────────

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

    # ── Edit / delete actions ────────────────────────────────────────────────

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
            self.vocab_store.save_word(
                record, saved_definition=dlg.saved_definition(), note=dlg.note(),
            )
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

    # ── Anki export ──────────────────────────────────────────────────────────

    def _export_anki(self) -> None:
        if not anki.is_available():
            QMessageBox.critical(
                self, "genanki not installed",
                "Install it with:\n\n    pip install genanki\n\nthen restart Kalima.",
            )
            return

        # If the parent window has an open book, pre-select that scope.
        book_id = ""
        book_title = ""
        mw = self.parent()
        if mw and hasattr(mw, "book") and mw.book.path:  # type: ignore[attr-defined]
            book_id = mw.book.book_id      # type: ignore[attr-defined]
            book_title = mw.book.title     # type: ignore[attr-defined]
        dlg = AnkiExportDialog(self.vocab_store, book_id, book_title, self)
        dlg.exec()
