"""
reader — Custom QWebEngine page + view for displaying EPUB chapters.

`ReaderPage`
    Intercepts navigation requests so:
    * ``lookup://word?value=X`` URLs (emitted by INSTALL_WORD_LOOKUP_JS when
      a word span is clicked) fire `wordLookupRequested` and are otherwise
      cancelled — they should never actually navigate.
    * In-EPUB links to other chapters (file://...) fire
      `chapterNavigationRequested` so the main window can sync the sidebar
      selection instead of letting WebEngine load the file unmanaged.

`ReaderView`
    Adds single-click word lookup, double-click selection lookup, and a
    right-click menu with Copy / Translate / Ask Claude / Ask ChatGPT /
    Ask AI… actions. Heavy lifting (running the actual lookup or AI
    prompt) is delegated upward via Qt signals.
"""

from __future__ import annotations

from urllib.parse import parse_qs, quote, unquote, urlparse

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QInputDialog, QMenu

from . import ollama
from .arabic import clean_lookup_word
from .config import WORD_AT_POINT_JS


class ReaderPage(QWebEnginePage):
    """Routes custom lookup:// URLs and chapter file:// links to the host."""

    chapterNavigationRequested = pyqtSignal(str)
    wordLookupRequested = pyqtSignal(str)

    def acceptNavigationRequest(  # noqa: N802 — Qt method name
        self,
        url: QUrl,
        nav_type: QWebEnginePage.NavigationType,
        is_main_frame: bool,
    ) -> bool:
        # Custom scheme used by INSTALL_WORD_LOOKUP_JS for clicked words.
        if url.scheme() == "lookup":
            parsed = urlparse(url.toString())
            qs = parse_qs(parsed.query)
            query_value = qs.get("value", [""])[0]
            word = clean_lookup_word(unquote(query_value))
            if word:
                self.wordLookupRequested.emit(word)
            return False  # never actually navigate

        # In-EPUB chapter link — let the host swap chapters cleanly.
        if (
            nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
            and url.isLocalFile()
        ):
            self.chapterNavigationRequested.emit(url.toLocalFile())
            return True

        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class ReaderView(QWebEngineView):
    """QWebEngineView with click-to-lookup and an AI-aware context menu.

    Signals
    -------
    wordClicked : str
        A single Arabic word the user clicked or double-tapped.
    aiActionRequested : (str, str)
        ``(action_id, selected_text)`` for a registered Ask AI… prompt.
    customAiRequested : (str, str)
        ``(prompt_template, selected_text)`` for the Ask Custom Prompt option.
    translateRequested : str
        Selected text the user wants to translate (host decides where).
    """

    wordClicked = pyqtSignal(str)
    aiActionRequested = pyqtSignal(str, str)
    customAiRequested = pyqtSignal(str, str)
    translateRequested = pyqtSignal(str)

    # ── Mouse handling ───────────────────────────────────────────────────────

    def mouseReleaseEvent(self, event):  # noqa: N802 — Qt method name, ANN001
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # Plain left click only; Cmd/Ctrl-clicks are reserved for other actions.
        if event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        ):
            return

        pos = event.position()
        # Small delay lets the browser update the selection before we read it.
        QTimer.singleShot(80, lambda: self._lookup_at_position(int(pos.x()), int(pos.y())))

    def mouseDoubleClickEvent(self, event):  # noqa: N802, ANN001
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

    # ── Right-click context menu ─────────────────────────────────────────────

    def contextMenuEvent(self, event) -> None:  # noqa: N802, ANN001
        selected = self.page().selectedText().strip()
        if not selected:
            # No selection — let Qt show its default menu (inspector, etc.)
            super().contextMenuEvent(event)
            return

        menu = QMenu(self)

        # Basic edit / web actions
        copy_action = menu.addAction("Copy")
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(selected))

        translate_action = menu.addAction("Translate on Google")
        translate_action.triggered.connect(lambda: self.translateRequested.emit(selected))

        menu.addSeparator()
        claude_action = menu.addAction("Ask Claude")
        claude_action.triggered.connect(lambda: self._open_web_ai("claude", selected))
        chatgpt_action = menu.addAction("Ask ChatGPT")
        chatgpt_action.triggered.connect(lambda: self._open_web_ai("chatgpt", selected))

        # Local Ollama prompts (only if loaded successfully at startup)
        if ollama.PROMPT_ACTIONS:
            menu.addSeparator()
            ai_menu = menu.addMenu("Ask AI")
            for act in ollama.PROMPT_ACTIONS:
                a = ai_menu.addAction(act["label"])
                a.triggered.connect(
                    lambda _checked, aid=act["id"], sel=selected:
                        self.aiActionRequested.emit(aid, sel)
                )
            ai_menu.addSeparator()
            custom_a = ai_menu.addAction("Ask Custom Prompt…")
            custom_a.triggered.connect(lambda: self._ask_custom(selected))

        # event.globalPos() (PyQt6 QContextMenuEvent does not expose globalPosition().toPoint())
        menu.exec(event.globalPos())

    def _ask_custom(self, selected: str) -> None:
        """Prompt for a user-supplied AI template, then fire customAiRequested."""
        prompt, ok = QInputDialog.getMultiLineText(
            self,
            "Custom AI Prompt",
            "Enter your prompt. Use {text} to refer to the selected passage:",
            "Explain this in the context of Arabic literature:\n\n{text}",
        )
        if ok and prompt.strip():
            self.customAiRequested.emit(prompt.strip(), selected)

    # ── External browser AIs ─────────────────────────────────────────────────

    @staticmethod
    def _open_web_ai(service: str, text: str) -> None:
        """Open Claude or ChatGPT with a pre-filled translation prompt."""
        prompt = (
            "Translate the following Arabic text to English and identify "
            "the most important vocabulary words with their meanings:\n\n"
            + text
        )
        encoded = quote(prompt)
        if service == "claude":
            url = QUrl(f"https://claude.ai/new?q={encoded}")
        else:
            url = QUrl(f"https://chatgpt.com/?q={encoded}")
        QDesktopServices.openUrl(url)
