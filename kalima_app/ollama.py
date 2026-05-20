"""
ollama — Local AI integration via the Ollama HTTP API.

This module is intentionally Qt-aware (it uses QThread for streaming) but
kept independent of any Kalima UI widgets so panels and dialogs can import
it cleanly.

Contents
--------
* `find_binary()` / `is_running()` / `installed_models()`
    Plain helpers for talking to a local Ollama install.

* `PROMPT_ACTIONS`
    Module-level list of AI actions loaded from ``assets/prompts.json``.
    `load_prompts()` mutates it in place — the right-click menu, the AI
    panel, and the model picker all read from this single source.

* `OllamaWorker`
    Background QThread that streams `/api/generate` tokens back via signals.

* `PullWorker`
    Background QThread that shells out to `ollama pull <model>`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.request as _urllib_req
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from .config import OLLAMA_BASE_URL, PROMPTS_PATH


# ── Plain helpers ─────────────────────────────────────────────────────────────

def find_binary() -> str:
    """Locate the ``ollama`` binary.

    Frozen .app bundles don't inherit the shell PATH, so we fall back to
    the common Homebrew locations after `shutil.which` fails.
    """
    found = shutil.which("ollama")
    if found:
        return found
    for candidate in (
        "/opt/homebrew/bin/ollama",   # Apple Silicon Homebrew
        "/usr/local/bin/ollama",      # Intel Homebrew
        "/usr/bin/ollama",
    ):
        if Path(candidate).exists():
            return candidate
    return "ollama"  # let the OS surface a clear "not found" error


def is_running() -> bool:
    """True if the Ollama server is responding on localhost."""
    try:
        req = _urllib_req.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
        with _urllib_req.urlopen(req, timeout=3):
            return True
    except Exception:  # noqa: BLE001 — any failure means "not running"
        return False


def installed_models() -> list[str]:
    """List the models the user has already pulled. Empty list on failure."""
    try:
        req = _urllib_req.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
        with _urllib_req.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:  # noqa: BLE001
        return []


# ── Prompt registry ───────────────────────────────────────────────────────────
#
# Loaded from ``assets/prompts.json`` once at app startup (see main.py).
# Kept as a module-level list so importers can read the latest contents
# without re-importing — same pattern as a singleton registry.

PROMPT_ACTIONS: list[dict] = []


def load_prompts() -> list[dict]:
    """Read ``assets/prompts.json`` and update `PROMPT_ACTIONS` in place.

    The returned list is the same object as `PROMPT_ACTIONS` after the call
    completes — callers can use either reference.
    """
    PROMPT_ACTIONS.clear()
    try:
        with PROMPTS_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        PROMPT_ACTIONS.extend(data.get("actions", []))
    except Exception as exc:  # noqa: BLE001 — surface but don't crash startup
        print(f"Warning: could not load prompts.json: {exc}")
    return PROMPT_ACTIONS


# ── Background workers (QThread) ──────────────────────────────────────────────

class OllamaWorker(QThread):
    """Stream tokens from ``/api/generate``.

    Signals
    -------
    token_ready : str
        Emitted for each text fragment streamed back.
    finished
        Emitted exactly once, after success / error / abort. (This shadows
        QThread.finished — connect to this for stop-button logic, since
        we emit it from `run()` ourselves rather than relying on Qt.)
    error_occurred : str
        Emitted with an error message when streaming fails.
    """

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
        """Request that the worker stop after its current chunk."""
        self._abort = True

    def run(self) -> None:  # noqa: D401 — QThread hook
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
                    except Exception:  # noqa: BLE001 — skip malformed chunk
                        continue
                    token = obj.get("response", "")
                    if token:
                        self.token_ready.emit(token)
                    if obj.get("done"):
                        break
        except Exception as exc:  # noqa: BLE001 — relay to UI
            self.error_occurred.emit(str(exc))
        finally:
            self.finished.emit()


class PullWorker(QThread):
    """Run ``ollama pull <model>`` in the background."""

    finished_ok = pyqtSignal()
    finished_err = pyqtSignal(str)

    def __init__(self, model_id: str, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._model_id = model_id

    def run(self) -> None:  # noqa: D401 — QThread hook
        try:
            result = subprocess.run(
                [find_binary(), "pull", self._model_id],
                capture_output=True,
                text=True,
                timeout=1800,  # 30 min — large models can be slow
            )
            if result.returncode == 0:
                self.finished_ok.emit()
            else:
                self.finished_err.emit(result.stderr.strip() or "Unknown error")
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))
