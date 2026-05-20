"""
icons — Render toolbar SVG icons with automatic light/dark coloring.

The bundled SVGs in `assets/icons/` use `currentColor` as their stroke/fill.
At render time we substitute a concrete hex color chosen from the current
QPalette so icons stay legible whether macOS is light or dark.
"""

from __future__ import annotations

from PyQt6.QtCore import QByteArray, QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

from .config import ICONS_DIR


def svg_icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    """Return a QIcon rendered from ``assets/icons/<name>.svg``.

    Parameters
    ----------
    name
        Base name of the SVG file (without extension).
    color
        Hex color to substitute for ``currentColor``. When None (default) the
        function picks light gray on dark toolbars and dark gray on light
        toolbars, based on the current QPalette window color.
    size
        Output pixmap size in device-independent pixels.

    Returns an empty QIcon if the SVG is missing.
    """
    # Auto-pick a foreground color based on the toolbar background lightness.
    if color is None:
        app = QApplication.instance()
        if app is not None:
            bg = app.palette().color(QPalette.ColorRole.Window)
            color = "#ececec" if bg.lightness() < 128 else "#3a3a3c"
        else:
            color = "#3a3a3c"

    path = ICONS_DIR / f"{name}.svg"
    if not path.exists():
        return QIcon()

    # Inline the color so QSvgRenderer doesn't need CSS support.
    svg_bytes = path.read_bytes().replace(b"currentColor", color.encode())
    renderer = QSvgRenderer(QByteArray(svg_bytes))

    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)
