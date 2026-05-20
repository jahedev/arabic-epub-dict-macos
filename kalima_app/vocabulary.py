"""
vocabulary — SQLite-backed vocabulary store.

Schema
------
* ``books``  — one row per opened EPUB (keyed by SHA-256 of the file).
* ``vocab``  — one row per saved word, scoped by ``book_id``. The
  ``(book_id, normalized_word)`` pair is unique, so re-saving a word
  updates the existing row.

`foreign_keys = ON` is enabled on every connection — without that pragma
SQLite ignores the FK declaration, allowing orphaned vocab records.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Optional

from .models import LookupRecord, SavedVocab
from .utils import app_now


class VocabularyStore:
    """Thin SQLite wrapper. Each public method opens its own connection."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Connection / schema ──────────────────────────────────────────────────

    def connect(self) -> sqlite3.Connection:
        """Return a new connection with Row factory + foreign keys enforced."""
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

    # ── Books table ──────────────────────────────────────────────────────────

    def upsert_book(self, book_id: str, title: str, file_name: str, file_path: str) -> None:
        """Insert or update the books row when a new EPUB is opened."""
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

    # ── Vocab queries used by the reader ─────────────────────────────────────

    def saved_words_for_book(self, book_id: str) -> list[str]:
        """All normalized_word values for one book — used to highlight matches."""
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
        """Insert or update a vocab row. Preserves the original ``saved_at``."""
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

    # ── Bulk queries used by export and browser ──────────────────────────────

    def vocab_for_export(self, book_id: Optional[str] = None) -> list[SavedVocab]:
        """Records for either one book (Anki current-book scope) or all books."""
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
        """Dump everything to UTF-8 BOM CSV (Excel-friendly)."""
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
        """All saved words, optionally filtered by a substring query."""
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

    # ── Row-to-dataclass conversion ──────────────────────────────────────────

    @staticmethod
    def _row_to_vocab(row: sqlite3.Row) -> SavedVocab:
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
