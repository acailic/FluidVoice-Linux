#!/usr/bin/env python3
"""Generate README media offline, from the real overlay renderer (no X11).

Outputs:
  docs/screenshots/demo.gif       animated end-to-end demo (pill + fake chat app)
  docs/social-preview.png         1280x640 card for the GitHub social preview

Run:  .venv/bin/python scripts/gen-doc-media.py
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fluidvoice.overlay import AudioLevels, PillRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_GIF = ROOT / "docs" / "screenshots" / "demo.gif"
OUT_SOCIAL = ROOT / "docs" / "social-preview.png"

FONT_DIR = Path("/usr/share/fonts/opentype/inter")
FONT_REG = FONT_DIR / "Inter-Regular.otf"
FONT_MED = FONT_DIR / "Inter-Medium.otf"
FONT_SEMI = FONT_DIR / "Inter-SemiBold.otf"

# One neutral-dark family, tinted toward slate (never pure black).
BG_TOP = (19, 19, 25)
BG_BOT = (13, 13, 18)
WIN_BG = (26, 26, 33)
WIN_BORDER = (45, 45, 56)
WIN_ROW = (33, 33, 41)
INK_DIM = (122, 122, 134)
INK = (224, 224, 232)
GOLD = (224, 176, 76)

RAW_WORDS = ("um can we push the standup to tuesday around 3 no wait 4 p.m. "
             "literal question mark").split()
POLISHED = "Can we push the standup to Tuesday at 4 p.m.?"
POLISHED_WORDS = POLISHED.split()


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def backdrop(w: int, h: int) -> Image.Image:
    """Vertical slate gradient with a faint radial lift behind the content."""
    bg = Image.new("RGB", (w, h))
    px = bg.load()
    for y in range(h):
        t = y / (h - 1)
        c = tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT))
        for x in range(w):
            px[x, y] = c
    lift = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(lift)
    d.ellipse((w * 0.18, h * 0.06, w * 0.82, h * 0.72), fill=26)
    lift = lift.filter(ImageFilter.GaussianBlur(90))
    gold_layer = Image.new("RGB", (w, h), (34, 30, 24))
    bg.paste(gold_layer, (0, 0), lift)
    return bg.convert("RGB")


# -- the fake focused app (a chat window the dictation types into) ------------

WIN = (110, 54, 850, 340)   # x0, y0, x1, y1
INPUT = (130, 294, 830, 328)
TITLEBAR_H = 34
BUBBLE_IN = (130, 146, 520, 188)
BUBBLE_OUT_Y = 92
SENT_Y = 232


def rounded(d, box, radius, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline,
                        width=width)


def draw_window(d, fonts, typed_words: list[str], caret_on: bool,
                sent: bool):
    rounded(d, WIN, 14, fill=WIN_BG, outline=WIN_BORDER)
    # title bar: neutral dots + title
    cy = WIN[1] + TITLEBAR_H // 2
    for i, x in enumerate((WIN[0] + 22 + i * 18 for i in range(3))):
        d.ellipse((x - 5, cy - 5, x + 5, cy + 5), fill=(54, 54, 65))
    tw = d.textlength("Messages", font=fonts["title"])
    d.text(((WIN[0] + WIN[2]) / 2 - tw / 2, cy - 8), "Messages",
           font=fonts["title"], fill=INK_DIM)

    # earlier messages (dim thread that motivates the reply)
    m1 = "team lunch at 12, you in?"
    m1w = d.textlength(m1, font=fonts["chat"]) + 28
    rounded(d, (WIN[2] - 14 - m1w, BUBBLE_OUT_Y, WIN[2] - 14,
                BUBBLE_OUT_Y + 42), 11, fill=(31, 31, 40))
    d.text((WIN[2] - 14 - m1w + 14, BUBBLE_OUT_Y + 12), m1,
           font=fonts["chat"], fill=(150, 150, 163))
    rounded(d, BUBBLE_IN, 11, fill=(34, 34, 43))
    d.text((BUBBLE_IN[0] + 14, BUBBLE_IN[1] + 12),
           "Morning! Where do we land for standup?",
           font=fonts["chat"], fill=(160, 160, 173))

    # sent bubble (after the dictation lands)
    if sent:
        text = POLISHED
        bw = d.textlength(text, font=fonts["chat"]) + 28
        box = (WIN[2] - 14 - bw, SENT_Y, WIN[2] - 14, SENT_Y + 42)
        rounded(d, box, 11, fill=(41, 41, 52))
        d.text((box[0] + 14, box[1] + 12), text, font=fonts["chat"], fill=INK)

    # input field + gold send affordance
    rounded(d, INPUT, 10, fill=WIN_ROW)
    send_cx, send_cy = INPUT[2] - 22, (INPUT[1] + INPUT[3]) / 2
    d.ellipse((send_cx - 12, send_cy - 12, send_cx + 12, send_cy + 12),
              fill=GOLD if typed_words or sent else (66, 60, 44))
    d.polygon((send_cx - 4, send_cy - 5, send_cx + 5, send_cy,
               send_cx - 4, send_cy + 5), fill=(24, 22, 16))
    ix, iy = INPUT[0] + 14, (INPUT[1] + INPUT[3]) / 2 - 9
    max_tx = send_cx - 24 - ix
    if typed_words:
        text = " ".join(typed_words)
        while len(text) > 1 and d.textlength(text, font=fonts["chat"]) > \
                max_tx:
            text = text.split(None, 1)[1]
        d.text((ix, iy), text, font=fonts["chat"], fill=INK)
        tx = ix + d.textlength(text, font=fonts["chat"]) + 5
    else:
        ph = "Message"
        d.text((ix, iy), ph, font=fonts["chat"], fill=(108, 108, 122))
        tx = ix + d.textlength(ph, font=fonts["chat"]) + 6
    if caret_on:
        d.rounded_rectangle((tx, iy + 1, tx + 2, iy + 17), 1, fill=GOLD)


def compose(base, pill_img, bottom_y=556):
    """Center the pill frame horizontally, anchored to a fixed bottom edge."""
    frame = base.copy()
    x = (frame.width - pill_img.width) // 2
    y = bottom_y - pill_img.height
    frame.paste(pill_img, (x, y), pill_img)
    return frame


def bg_with_window(bg, fonts, typed_words=None, caret=False, sent=False):
    img = bg.copy()
    d = ImageDraw.Draw(img)
    draw_window(d, fonts, typed_words or [], caret, sent)
    return img


# -- GIF ----------------------------------------------------------------------

def speech_pcm(words_frames, n_frames, rate=16000, dt=0.085, seed=7):
    """PCM with one burst per spoken word, aligned to `words_frames`."""
    rng = random.Random(seed)
    n = int(rate * dt)
    pcm = bytearray()
    bursts = {f: rng.uniform(0.55, 1.0) for f in words_frames}
    for fi in range(n_frames):
        amp = 0.0
        for start, a in bursts.items():
            t = (fi - start) * dt
            if 0.0 <= t < 0.30:                      # ~300 ms word burst
                amp = max(amp, a * math.sin(math.pi * t / 0.30))
        wobble = 0.72 + 0.28 * math.sin(2 * math.pi * 4.5 * fi * dt)
        for i in range(n):
            s = amp * wobble * 0.72 * math.sin(
                2 * math.pi * 190 * i / rate) \
                + amp * wobble * 0.28 * math.sin(2 * math.pi * 470 * i / rate)
            pcm += int(max(-1.0, min(1.0, s)) * 24000).to_bytes(2, "little",
                                                                signed=True)
    return bytes(pcm), rate, n


def build_gif():
    W, H = 960, 580
    bg = backdrop(W, H)
    renderer = PillRenderer(size="large")
    levels = AudioLevels(rate=16000)

    fonts = {
        "title": font(FONT_MED, 14),
        "chat": font(FONT_REG, 15),
        "hint": font(FONT_MED, 14),
    }

    # -- schedule --------------------------------------------------------
    rec_frames = len(RAW_WORDS) * 2           # a word every 2 frames
    word_at = {i * 2: w for i, w in enumerate(RAW_WORDS)}
    proc_n, fade_n = 9, 4
    type_n, blink_n, send_n, hold_n = len(POLISHED_WORDS), 6, 3, 5

    pcm, rate, _ = speech_pcm(set(word_at), rec_frames)
    step = int(rate * 0.085) * 2              # bytes per frame

    frames: list[Image.Image] = []
    durations: list[int] = []

    def add(img, ms):
        frames.append(img)
        durations.append(ms)

    # 1) recording: waveform + streaming partials (+ hotkey hint at the start)
    for i in range(rec_frames):
        levels.update(pcm[: (i + 1) * step])
        text = " ".join(w for f, w in word_at.items() if f <= i)
        pill, _ = renderer.render(levels.levels(), text,
                                  state="recording", phase=i * 0.09)
        img = compose(bg_with_window(bg, fonts), pill)
        if i < 5:                             # hint chip fades over 5 frames
            a = 1.0 - i / 5.0
            d = ImageDraw.Draw(img, "RGBA")
            txt = "Right Ctrl"
            tw = d.textlength(txt, font=fonts["hint"])
            cx, cy = W / 2, 556 - pill.height - 46
            d.rounded_rectangle((cx - tw / 2 - 12, cy - 10, cx + tw / 2 + 12,
                                 cy + 16), 9,
                                fill=(24, 24, 31, int(215 * a)),
                                outline=(58, 58, 70, int(255 * a)))
            d.text((cx - tw / 2, cy - 6), txt, font=fonts["hint"],
                   fill=(200, 200, 212, int(255 * a)))
        add(img, 85)

    full_raw = " ".join(RAW_WORDS)
    window_base = bg_with_window(bg, fonts)

    # 2) processing (final whisper pass)
    for i in range(proc_n):
        pill, _ = renderer.render([0] * levels.bars, full_raw,
                                  state="processing", phase=i * 0.16)
        add(compose(window_base, pill), 110)

    # 3) pill fades, text is about to be inserted
    for i in range(fade_n):
        pill, _ = renderer.render([0] * levels.bars, full_raw,
                                  state="processing", phase=1.0,
                                  alpha=1.0 - (i + 1) / fade_n)
        add(compose(window_base, pill), 55)

    # 4) polished text types into the focused app
    for i in range(type_n):
        add(bg_with_window(bg, fonts, POLISHED_WORDS[: i + 1], True), 130)
    for i in range(blink_n):
        add(bg_with_window(bg, fonts, POLISHED_WORDS, i % 2 == 0), 220)
    for i in range(send_n):                   # message sends, input clears
        add(bg_with_window(bg, fonts, [], True, sent=True), 150)
    for i in range(hold_n):
        add(bg_with_window(bg, fonts, [], i % 2 == 1, sent=True), 420)

    # -- one shared palette so the loop never flickers -------------------
    sheet = Image.new("RGB", (W * 4, H * 3))
    for k, idx in enumerate(range(0, len(frames), max(1, len(frames) // 12))):
        m = frames[idx].convert("RGB")
        sheet.paste(m, ((k % 4) * W, (k // 4) * H))
    pal = sheet.quantize(colors=255, method=Image.MEDIANCUT)
    pal_frames = [f.convert("RGB").quantize(palette=pal, dither=Image.NONE)
                  for f in frames]

    OUT_GIF.parent.mkdir(parents=True, exist_ok=True)
    pal_frames[0].save(OUT_GIF, save_all=True, append_images=pal_frames[1:],
                       duration=durations, loop=0, optimize=True,
                       disposal=2)
    print(f"{OUT_GIF}: {len(pal_frames)} frames, "
          f"{OUT_GIF.stat().st_size / 1e6:.2f} MB, "
          f"{sum(durations) / 1000:.1f} s loop")


# -- social preview card --------------------------------------------------------

def build_social():
    W, H = 1280, 640
    img = backdrop(W, H)
    d = ImageDraw.Draw(img)

    icon = Image.open(ROOT / "fluidvoice" / "assets" / "icon.png").convert(
        "RGBA").resize((216, 216), Image.LANCZOS)
    img.paste(icon, ((W - icon.width) // 2, 96), icon)

    name = "SayItErmano"
    f_name = font(FONT_SEMI, 88)
    d.text(((W - d.textlength(name, font=f_name)) / 2, 350), name,
           font=f_name, fill=(240, 240, 246))

    tag = "SayItErmano — local voice dictation with AI polish"
    f_tag = font(FONT_MED, 33)
    d.text(((W - d.textlength(tag, font=f_tag)) / 2, 470), tag,
           font=f_tag, fill=(178, 178, 192))

    chips = "100% LOCAL   ·   WHISPER   ·   GTK 4   ·   GPL-3.0"
    f_chip = font(FONT_SEMI, 23)
    d.text(((W - d.textlength(chips, font=f_chip)) / 2, 532), chips,
           font=f_chip, fill=(150, 150, 164))

    # waveform motif: the pill's bars, echoed along the bottom
    rng = random.Random(11)
    n, bw, gap = 64, 6, 10
    total = n * bw + (n - 1) * gap
    x = (W - total) / 2
    for i in range(n):
        hgt = 9 + (math.sin(i / n * math.pi) ** 2) * rng.uniform(6, 26)
        a = int(70 + 130 * math.sin(i / n * math.pi))
        d.rounded_rectangle((x, 610 - hgt, x + bw, 610), 3,
                            fill=(224, 176, 76, a))
        x += bw + gap

    OUT_SOCIAL.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_SOCIAL)
    print(f"{OUT_SOCIAL}: {img.size}")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("gif", "all"):
        build_gif()
    if which in ("social", "all"):
        build_social()
