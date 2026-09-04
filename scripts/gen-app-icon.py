#!/usr/bin/env python3
"""Generate the SayItErmano app icon (original artwork, no FluidVoice assets).

Three palette variants; the chosen one is installed into
  - fluidvoice/assets/icon.png            (tray + overlay pill)
  - fluidvoice/assets/icons/sayit-ermano.png
  - packaging/icons/hicolor/<n>/apps/sayit-ermano.png

Usage: scripts/gen-app-icon.py [fiesta|noche|sol] [--install]
Without --install renders preview PNGs into design/icons/ only.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent

# name -> bg top-left, bg bottom-right, bubble, bar colors, sparkle
PALETTES = {
    "fiesta": dict(bg=("#E8452C", "#A50E1E"), bubble=(255, 251, 244, 255),
                   bars=["#C1121F", "#E85D04", "#F1BF00", "#C1121F"],
                   sparkle=(255, 216, 77, 255)),
    "noche": dict(bg=("#2A3050", "#12141F"), bubble=(241, 191, 0, 255),
                  bars=["#232840", "#3A2A00", "#FFFFFF", "#232840"],
                  sparkle=(255, 244, 214, 255)),
    "sol":   dict(bg=("#FFD24A", "#F49A18"), bubble=(255, 255, 255, 255),
                  bars=["#AA151B", "#D62828", "#E85D04", "#AA151B"],
                  sparkle=(192, 18, 31, 255)),
}


def _gradient(size: int, top: str, bottom: str) -> Image.Image:
    """Smooth diagonal (top-left -> bottom-right) two-color gradient."""
    import numpy as np
    top_rgb = tuple(int(top[i:i + 2], 16) for i in (1, 3, 5))
    bot_rgb = tuple(int(bottom[i:i + 2], 16) for i in (1, 3, 5))
    y, x = np.mgrid[0:size, 0:size].astype(float)
    t = ((x + y) / (2 * (size - 1))) ** 1.1          # slight power = richer
    arr = np.stack([top_rgb[i] * (1 - t) + bot_rgb[i] * t
                    for i in range(3)], axis=-1).astype("uint8")
    return Image.fromarray(arr, "RGB").convert("RGBA")


def _hex(c: str) -> tuple[int, int, int, int]:
    v = tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
    return (*v, 255)


def _sparkle(d: ImageDraw.Draw, cx: int, cy: int, r: int, color) -> None:
    """4-point star (concave diamond)."""
    q = max(1, r // 4)
    d.polygon([(cx, cy - r), (cx + q, cy - q), (cx + r, cy), (cx + q, cy + q),
               (cx, cy + r), (cx - q, cy + q), (cx - r, cy), (cx - q, cy - q)],
              fill=color)


def render(size: int, palette: str = "fiesta") -> Image.Image:
    p = PALETTES[palette]
    s = size

    def S(v: float) -> int:  # design laid out on a 512 grid
        return max(1, round(v * s / 512))

    img = _gradient(s, *p["bg"])
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    # speech bubble: rounded rect with one clean wedge tail (top edge of the
    # wedge sits inside the bubble so the union has no seams)
    bx0, by0, bx1, by1 = S(108), S(116), S(404), S(300)
    ld.rounded_rectangle((bx0, by0, bx1, by1), S(60), fill=p["bubble"])
    ld.polygon([(S(150), S(292)), (S(258), S(292)), (S(180), S(378))],
               fill=p["bubble"])

    # waveform bars inside the bubble (pill shapes), comfortable padding
    bw, gap = S(38), S(24)
    heights = [S(70), S(126), S(92), S(150)]
    total = 4 * bw + 3 * gap
    x = bx0 + ((bx1 - bx0) - total) // 2
    cy = (by0 + by1) // 2
    for i, h in enumerate(heights):
        ld.rounded_rectangle((x, cy - h // 2, x + bw, cy + h // 2),
                             radius=bw // 2, fill=_hex(p["bars"][i]))
        x += bw + gap

    if s > 48:
        _sparkle(ld, S(408), S(106), S(34), p["sparkle"])

    img.alpha_composite(layer)

    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, s - 1, s - 1), round(s * 0.22), fill=255)
    return Image.composite(img, Image.new("RGBA", (s, s), (0, 0, 0, 0)), mask)


def install(palette: str) -> None:
    master = render(512, palette)
    targets = {
        REPO / "fluidvoice/assets/icon.png": render(512, palette),
        REPO / "fluidvoice/assets/icons/sayit-ermano.png": render(512, palette),
    }
    for size in (16, 32, 48, 64, 128, 256, 512):
        targets[REPO / f"packaging/icons/hicolor/{size}x{size}/apps/"
                f"sayit-ermano.png"] = (render(size, palette) if size <= 64
                                        else master.resize(
                                            (size, size), Image.LANCZOS))
    for path, img in targets.items():
        img.save(path)
        print(f"wrote {path.relative_to(REPO)} ({img.size[0]}px)")


if __name__ == "__main__":
    palette = next((a for a in sys.argv[1:] if not a.startswith("--")),
                   "fiesta")
    if "--install" in sys.argv:
        install(palette)
    else:
        out = REPO / "design/icons"
        out.mkdir(parents=True, exist_ok=True)
        for name in PALETTES:
            for size in (512, 64, 32):
                render(size, name).save(out / f"{name}-{size}.png")
        print(f"previews in {out}")
