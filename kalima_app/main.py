"""
main — Entry point invoked by the top-level ``kalima.py`` script.

Responsibilities
----------------
1. Load the prompt registry from ``assets/prompts.json`` before any window
   is constructed (the reader's right-click menu reads it at build time).
2. Bring up the Qt application, the main window, and show it.
3. Warn the user if macOS PyObjC DictionaryServices is missing (the rest
   of the app still works — only word lookup is degraded).
"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from . import ollama
from .arabic import DCSCopyTextDefinition
from .config import APP_NAME, APP_ORG
from .main_window import MainWindow


def main() -> int:
    """Construct the Qt app, show the window, and return the exit code."""
    # Populate the prompt registry. The reader's right-click menu reads
    # `ollama.PROMPT_ACTIONS` directly, so this must happen before MainWindow.
    ollama.load_prompts()

    app = QApplication(sys.argv)
    app.setOrganizationName(APP_ORG)
    app.setApplicationName(APP_NAME)

    window = MainWindow()
    window.show()

    # Soft-fail when running outside macOS or without PyObjC — keep the
    # reader functional, just warn that lookup won't work.
    if DCSCopyTextDefinition is None:
        QMessageBox.warning(
            window,
            "Dictionary Services unavailable",
            "The reader will open, but word lookup needs macOS PyObjC DictionaryServices.\n\n"
            "Install it with:\n"
            "pip install pyobjc-framework-DictionaryServices",
        )

    return app.exec()
