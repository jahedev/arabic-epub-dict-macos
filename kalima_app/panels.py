"""
panels — Side-panel widgets and Ollama-related dialogs.

Contents
--------
`TranslatePanel`
    Embedded QWebEngineView showing Google Translate in-app.

`OllamaSetupDialog`
    Shown when the Ollama server isn't reachable. Explains install
    options and recommends models.

`ModelManagerDialog`
    Lists recommended models with install status. Lets the user kick off
    ``ollama pull`` from inside the app.

`OllamaPanel`
    The right-hand AI sidebar — model picker, streaming response view,
    and stop button. Hosts an `OllamaWorker` per request.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QSettings, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import ollama
from .config import RECOMMENDED_MODELS


# ── In-app Google Translate panel ─────────────────────────────────────────────

class TranslatePanel(QWidget):
    """Sidebar that embeds a QWebEngineView to show Google Translate in-app."""

    closeRequested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
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
        """Navigate the embedded view (called by MainWindow on translate)."""
        self._view.load(url)

    def _open_in_browser(self) -> None:
        QDesktopServices.openUrl(self._view.url())


# ── Setup dialog (shown when Ollama isn't reachable) ──────────────────────────

class OllamaSetupDialog(QDialog):
    """Explains how to install Ollama and which models to pull."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
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

        # ── Install instructions
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

        # ── Model recommendations
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

        # ── Buttons
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
        """Re-probe the Ollama server, close on success."""
        if ollama.is_running():
            self.accept()
        else:
            QMessageBox.warning(
                self, "Not found",
                "Ollama is still not reachable at localhost:11434.",
            )


# ── Model manager (pull-from-the-app) ─────────────────────────────────────────

class ModelManagerDialog(QDialog):
    """Lists recommended models and offers to ``ollama pull`` missing ones."""

    def __init__(self, installed: list[str], parent: Optional[QWidget] = None) -> None:
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
            # ollama tag names sometimes include a registry prefix, so use `in`
            is_installed = any(m["id"] in name for name in installed)
            row = QHBoxLayout()
            name_lbl = QLabel(f"<b>{m['id']}</b>  ({m['ram']})")
            name_lbl.setMinimumWidth(270)
            status_lbl = QLabel("✓ Installed" if is_installed else "Not installed")
            status_lbl.setStyleSheet("color: green;" if is_installed else "color: gray;")
            pull_btn = QPushButton("Pull")
            pull_btn.setEnabled(not is_installed)
            pull_btn.clicked.connect(
                lambda _checked, mid=m["id"], sl=status_lbl, pb=pull_btn:
                    self._pull(mid, sl, pb)
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

    def _pull(self, model_id: str, status_lbl: QLabel, pull_btn: QPushButton) -> None:
        pull_btn.setEnabled(False)
        status_lbl.setText("Downloading… (may take several minutes)")
        status_lbl.setStyleSheet("color: orange;")
        worker = ollama.PullWorker(model_id, self)
        worker.finished_ok.connect(lambda: self._pull_done(status_lbl, True))
        worker.finished_err.connect(lambda err: self._pull_done(status_lbl, False, err))
        worker.start()
        # Keep a reference so the QThread isn't garbage collected mid-download.
        self._current_pull = worker

    def _pull_done(self, status_lbl: QLabel, ok: bool, err: str = "") -> None:
        if ok:
            status_lbl.setText("✓ Installed")
            status_lbl.setStyleSheet("color: green;")
        else:
            status_lbl.setText(f"Failed: {err}")
            status_lbl.setStyleSheet("color: red;")


# ── The main AI sidebar ───────────────────────────────────────────────────────

class OllamaPanel(QWidget):
    """Resizable side panel that runs AI prompts via Ollama and streams output."""

    def __init__(self, settings: QSettings, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._worker: Optional[ollama.OllamaWorker] = None
        self.setMinimumWidth(240)

        # ── Header
        header = QLabel("AI Assistant")
        header.setStyleSheet("font-weight: bold; font-size: 13px;")

        manage_btn = QPushButton("Models…")
        manage_btn.setToolTip("Manage recommended models")
        manage_btn.clicked.connect(self._manage_models)

        header_row = QHBoxLayout()
        header_row.addWidget(header)
        header_row.addStretch()
        header_row.addWidget(manage_btn)

        # ── Model picker
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

        # ── Action label (which prompt is running)
        self._action_label = QLabel("")
        self._action_label.setStyleSheet("color: gray; font-size: 11px;")
        self._action_label.setWordWrap(True)

        # ── Streaming response
        self.response_view = QTextEdit()
        self.response_view.setReadOnly(True)
        self.response_view.setPlaceholderText(
            "Select text in the reader and right-click → Ask AI…"
        )

        # ── Stop button (visible only while generating)
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

    # ── Model list management ────────────────────────────────────────────────

    def refresh_models(self) -> None:
        """Re-query Ollama for installed models and update the dropdown."""
        models = ollama.installed_models()
        prev = self.model_combo.currentText()
        self.model_combo.clear()
        if models:
            self.model_combo.addItems(models)
            # Try to restore the previous selection first, then fall back to
            # the persisted preference from QSettings.
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

        # Persist whichever model the user actively selects.
        self.model_combo.currentTextChanged.connect(
            lambda t: self._settings.setValue("ai_model", t)
        )

    def current_model(self) -> str:
        return self.model_combo.currentText()

    # ── Running a prompt ─────────────────────────────────────────────────────

    def run_action(self, action_id: str, text: str, custom_prompt: str = "") -> None:
        """Execute a prompt either from the registry or a custom template.

        ``action_id == 'custom'`` uses ``custom_prompt`` (with optional
        ``{text}`` interpolation). Otherwise we look the action up in
        ``ollama.PROMPT_ACTIONS``.
        """
        # If Ollama isn't running, walk the user through setup first.
        if not ollama.is_running():
            dlg = OllamaSetupDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            self.refresh_models()

        if action_id == "custom":
            system = "You are a helpful Arabic language assistant."
            if "{text}" in custom_prompt:
                prompt = custom_prompt.replace("{text}", text)
            else:
                # No placeholder → just append the passage.
                prompt = custom_prompt + "\n\n" + text
            label = custom_prompt[:60] + ("…" if len(custom_prompt) > 60 else "")
        else:
            action = next((a for a in ollama.PROMPT_ACTIONS if a["id"] == action_id), None)
            if action is None:
                return
            system = action.get("system", "")
            prompt = action["user_template"].replace("{text}", text)
            label = action["label"]

        model = self.current_model()
        if not model or model.startswith("("):
            QMessageBox.warning(
                self, "No model selected",
                "Please select a valid model from the dropdown.",
            )
            return

        preview = text[:60] + ("…" if len(text) > 60 else "")
        self._action_label.setText(f"{label}  ·  “{preview}”")
        self.response_view.clear()
        self._stop_btn.setVisible(True)

        # Make sure any previous generation is stopped before we start a new one.
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait()

        self._worker = ollama.OllamaWorker(model=model, system=system, prompt=prompt)
        self._worker.token_ready.connect(self._append_token)
        self._worker.finished.connect(self._on_finished)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    # ── Streaming output handlers ────────────────────────────────────────────

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

    # ── Model manager launcher ───────────────────────────────────────────────

    def _manage_models(self) -> None:
        installed = ollama.installed_models()
        dlg = ModelManagerDialog(installed, self)
        dlg.exec()
        self.refresh_models()
