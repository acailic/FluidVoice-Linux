"""Suite-wide process-state guards.

Loaded before any test module is imported (pytest imports conftest first),
which is exactly what the Pillow warm-up below needs.
"""
from __future__ import annotations


def _warm_pillow_freetype() -> None:
    """Load one Pillow truetype face before GTK/Pango can render text.

    Pillow wheels vendor their own FreeType/HarfBuzz (pillow.libs). If the
    first face load happens AFTER Pango has rendered in this process, every
    later Pillow text measurement returns garbage (negative or huge
    advances) - pill widths collapse and test_overlay renders
    hundred-megapixel canvases, but only when a gtkui test ran first, so it
    reads as an unexplained order dependency. Loading any face (and walking
    one glyph advance) before the first test pins the vendored library into
    a good state for the whole session. No-op when no system font exists
    (headless CI): overlay falls back to load_default there and no gtkui
    test runs without a display anyway.
    """
    try:
        from fluidvoice.overlay import _load_font

        font = _load_font(13, bold=True)
        if font is not None:
            font.getlength("warm")
    except Exception:
        pass  # measurement guards must never break collection


_warm_pillow_freetype()
