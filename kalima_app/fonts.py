"""
fonts — Discover bundled Arabic reader fonts in ``assets/fonts/``.

Each ``.ttf`` becomes a `FontOption` the user can pick from the toolbar.
The display name is derived from the file stem with the weight/style
suffix stripped (so ``Amiri-Regular.ttf`` displays as ``Amiri``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import FONTS_DIR


# Strip "-Regular", "-Bold", "-Italic", "-Light", etc. (and anything after)
# from font file stems before showing them in the picker.
_FONT_WEIGHT_RE = re.compile(
    r"-(Regular|Bold|Italic|Light|Medium|SemiBold|ExtraBold|Black|Thin|Variable).*$",
    re.IGNORECASE,
)


@dataclass
class FontOption:
    """One entry in the reader-font dropdown."""

    display_name: str            # shown in the picker (e.g. "Amiri")
    css_family: str              # value used inside font-family
    file_path: Optional[Path]    # .ttf path, or None for "System Default"


def camel_to_spaces(s: str) -> str:
    """Convert ``CamelCase`` to ``Camel Case``, preserving acronyms."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", s)
    return s.strip()


def load_font_options() -> list[FontOption]:
    """Return [System Default, ...bundled fonts] sorted alphabetically."""
    options: list[FontOption] = [
        FontOption(
            display_name="System Default",
            css_family="-apple-system, BlinkMacSystemFont, 'Geeza Pro', Arial, serif",
            file_path=None,
        )
    ]
    if FONTS_DIR.exists():
        for ttf in sorted(FONTS_DIR.glob("*.ttf")):
            stem = _FONT_WEIGHT_RE.sub("", ttf.stem)
            display = camel_to_spaces(stem)
            options.append(
                FontOption(display_name=display, css_family=display, file_path=ttf)
            )
    return options
