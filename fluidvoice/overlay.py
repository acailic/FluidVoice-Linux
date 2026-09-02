"""Mac-style recording overlay (Linux port of the upstream macOS
BottomOverlayView): a bottom-center, always-on-top, never-focusable pill.

Solid black stadium with a subtle gloss border, the app icon, a live
waveform driven by the microphone level, and - once partial results exist -
a line of streaming transcription above the waveform row. While the final
pass runs the bars flatten and a shimmer sweeps across them, the same
choreography as on the Mac.

Rendering is pure Pillow so it is testable headless. The X11 side pushes
RGBA frames through a 32-bit visual when a compositor is available, falls
back to a shaped opaque window, and finally to replaceable desktop
notifications (NotifyPreview) - preserving the old graceful degradation.
"""
from __future__ import annotations

import array
import math
import threading
import time
from pathlib import Path

# Mac pill spec (upstream LayoutConstants for .pill / .small)
PILL_H = 46
PILL_RADIUS = 23          # stadium: height/2
PAD_H = 12
PAD_V = 8
ICON_SIZE = 18
ICON_GAP = 8
BAR_COUNT = 8
BAR_W = 3.0
BAR_GAP = 2.5
BAR_MIN_H = 4
BAR_MAX_H = 28
BARS_WIDTH = BAR_COUNT * BAR_W + (BAR_COUNT - 1) * BAR_GAP  # 41.5
WAVE_W = 46
WAVE_H = 30
LABEL = "Dictate"
LABEL_SIZE = 10
TEXT_SIZE = 13
TEXT_LINE_H = 20
TEXT_GAP = 6
TEXT_RADIUS = 16          # rounded rect once preview text is shown
MAX_TEXT_W = 560
BOTTOM_OFFSET = 64        # px above the screen bottom edge
MAX_FRAME_BYTES = 800_000  # conservative XPutImage request cap

BAR_ALPHA = 224           # white @ 0.88 while recording
BAR_FLAT_ALPHA = 82       # white @ 0.32 while processing
LABEL_ALPHA = 217         # white @ 0.85
TEXT_ALPHA = 230          # white @ 0.9
BORDER_ALPHA_TOP = 76     # gloss: bright top fading to dim bottom
BORDER_ALPHA_BOTTOM = 26
SHIMMER_PERIOD = 1.05     # seconds per sweep (upstream CompositorShimmerSweep)
PROCESSING_CAP = 15.0     # hard auto-close so a hung pipeline never strands it

_FONT_DIRS = (
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/noto",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/dejavu",
    "/usr/share/fonts",
)
_REGULAR = ("DejaVuSans.ttf", "NotoSans-Regular.ttf", "LiberationSans-Regular.ttf")
_BOLD = ("DejaVuSans-Bold.ttf", "NotoSans-Bold.ttf", "LiberationSans-Bold.ttf")


def _find_font(bold: bool) -> str | None:
    for d in _FONT_DIRS:
        for name in (_BOLD if bold else _REGULAR):
            p = Path(d) / name
            if p.exists():
                return str(p)
    return None


def _load_font(size: int, bold: bool):
    from PIL import ImageFont
    path = _find_font(bold)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def head_truncate(draw, text: str, font, max_w: int) -> str:
    """Clip the HEAD of long streaming text: keep the newest words."""
    if draw.textlength(text, font=font) <= max_w or len(text) < 2:
        return text
    out = "…" + text[1:]
    while len(out) > 2 and draw.textlength(out, font=font) > max_w:
        out = "…" + out[2:]
    return out


def _load_default_icon():
    try:
        from importlib import resources
        ref = resources.files("fluidvoice.assets").joinpath("icon.png")
        with resources.as_file(ref) as p:
            return str(p)
    except Exception:
        return None


class PillRenderer:
    """Renders pill frames as RGBA images (pure Pillow, no X11)."""

    SS = 2   # supersample factor for anti-aliasing
    MARGIN = 22  # transparent margin: room for the drop shadow (blur tail ~3*sigma)

    def __init__(self, icon_path: str | Path | None = None):
        from PIL import Image
        self._Image = Image
        # fonts are painted on the supersampled canvas, so scale by SS and
        # divide textlength by SS wherever 1x geometry is needed
        self._label_font = _load_font(LABEL_SIZE * self.SS, bold=True)
        self._text_font = _load_font(TEXT_SIZE * self.SS, bold=False)
        self._icon = self._load_icon(icon_path or _load_default_icon())
        self._cache: dict = {}

    def _load_icon(self, icon_path):
        try:
            img = self._Image.open(icon_path).convert("RGBA")
        except Exception:
            return None
        return img.resize((ICON_SIZE * self.SS, ICON_SIZE * self.SS),
                          self._Image.LANCZOS)

    # -- geometry -----------------------------------------------------------

    def _row_width(self) -> int:
        from PIL import ImageDraw
        probe = self._Image.new("RGBA", (4, 4))
        label_w = ImageDraw.Draw(probe).textlength(
            LABEL, font=self._label_font) / self.SS
        w = 0
        if self._icon is not None:
            w += ICON_SIZE + ICON_GAP
        w += WAVE_W + 10 + int(label_w)
        return w

    def inner_size(self, text: str | None) -> tuple[int, int, int]:
        """(pill width, pill height, radius) without the shadow margin."""
        from PIL import ImageDraw
        row_w = self._row_width()
        inner_w = row_w
        h = PILL_H
        radius = PILL_RADIUS
        if text:
            probe = self._Image.new("RGBA", (4, 4))
            d = ImageDraw.Draw(probe)
            text = head_truncate(d, text, self._text_font, MAX_TEXT_W * self.SS)
            tw = int(d.textlength(text, font=self._text_font) / self.SS)
            inner_w = max(row_w, tw)
            h = PAD_V + TEXT_LINE_H + TEXT_GAP + WAVE_H + PAD_V
            radius = TEXT_RADIUS
        return inner_w + 2 * PAD_H, h, radius

    def measure(self, text: str | None) -> tuple[int, int]:
        """Outer size (pill + shadow margin) - also the X11 window size."""
        w, h, _ = self.inner_size(text)
        return w + 2 * self.MARGIN, h + 2 * self.MARGIN

    # -- painting -----------------------------------------------------------

    def render(self, levels, text: str | None = None, *, processing: bool = False,
               phase: float = 0.0, alpha: float = 1.0):
        """One frame -> (RGBA image, (w, h), L-mode alpha of pill+shadow)."""
        from PIL import Image
        w, h, radius = self.inner_size(text)
        ow = w + 2 * self.MARGIN
        oh = h + 2 * self.MARGIN

        frame = self._shadow_layer(ow, oh, radius)
        inner = Image.new("RGBA", (w * self.SS, h * self.SS), (0, 0, 0, 0))
        self._paint(inner, levels, text, processing, phase, radius)
        inner = inner.resize((w, h), Image.LANCZOS)
        frame.alpha_composite(inner, (self.MARGIN, self.MARGIN))
        if alpha < 1.0:
            frame.putalpha(frame.getchannel("A").point(lambda a: int(a * alpha)))
        return frame, (ow, oh)

    def _paint(self, im, levels, text, processing, phase, radius):
        from PIL import Image, ImageDraw
        S = self.SS
        W, H = im.size
        d = ImageDraw.Draw(im)

        d.rounded_rectangle((0, 0, W - 1, H - 1), radius * S, fill=(0, 0, 0, 255))
        im.alpha_composite(self._gloss_border(W, H, radius))

        row_w = self._row_width()
        row_y = (H - WAVE_H * S) // 2 if not text \
            else (PAD_V + TEXT_LINE_H + TEXT_GAP) * S
        x = (W - row_w * S) // 2

        if self._icon is not None:
            icon_y = row_y + (WAVE_H * S - ICON_SIZE * S) // 2
            im.alpha_composite(self._rounded_icon(), (int(x), int(icon_y)))
            x += (ICON_SIZE + ICON_GAP) * S

        self._paint_bars(d, x + (WAVE_W - BARS_WIDTH) / 2 * S, row_y,
                         levels, processing, phase)
        x += WAVE_W * S + 10 * S

        label_a = LABEL_ALPHA if not processing else int(LABEL_ALPHA * 0.5)
        d.text((x, row_y + (WAVE_H * S - LABEL_SIZE * S) // 2 + S), LABEL,
               font=self._label_font, fill=(255, 255, 255, label_a))

        if text:
            text = head_truncate(d, text, self._text_font, MAX_TEXT_W * S)
            d.text((PAD_H * S, PAD_V * S), text, font=self._text_font,
                   fill=(255, 255, 255, TEXT_ALPHA))

    def _gloss_border(self, W, H, radius):
        """Subtle gloss: brighter top edge fading toward the bottom."""
        from PIL import Image, ImageChops, ImageDraw
        key = ("gloss", W, H, radius)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        outline = Image.new("L", (W, H), 0)
        ImageDraw.Draw(outline).rounded_rectangle(
            (0, 0, W - 1, H - 1), radius * self.SS, outline=255,
            width=max(2, int(1.2 * self.SS)))
        grad = Image.linear_gradient("L").resize((W, H))
        scale = Image.new("L", (W, H), BORDER_ALPHA_TOP)
        scale.paste(Image.new("L", (W, H), BORDER_ALPHA_BOTTOM), (0, 0, W, H),
                    grad.point(lambda v: v))
        border = Image.new("RGBA", (W, H), (255, 255, 255, 0))
        border.putalpha(ImageChops.multiply(outline, scale))
        self._cache[key] = border
        return border

    def _rounded_icon(self):
        from PIL import Image, ImageChops, ImageDraw
        key = "icon"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        size = ICON_SIZE * self.SS
        r = int(size * 0.3)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), r,
                                               fill=255)
        out = self._icon.copy()
        out.putalpha(ImageChops.multiply(out.getchannel("A"), mask))
        self._cache[key] = out
        return out

    def _paint_bars(self, d, x, row_y, levels, processing, phase):
        S = self.SS
        heights = list(levels) if levels else []
        heights += [BAR_MIN_H] * (BAR_COUNT - len(heights))
        heights = [min(max(h, BAR_MIN_H), BAR_MAX_H) for h in heights[:BAR_COUNT]]
        sweep = (phase % SHIMMER_PERIOD) / SHIMMER_PERIOD  # 0..1 left..right
        for i, bh in enumerate(heights):
            bx = x + i * (BAR_W + BAR_GAP) * S
            bh_px = bh * S
            y0 = row_y + (WAVE_H * S - bh_px) / 2
            if processing:
                # flat bars + shimmer sweep across the waveform
                center = (i + 0.5) / BAR_COUNT
                dist = abs(center - sweep)
                boost = math.exp(-((dist / 0.16) ** 2))
                a = int(BAR_FLAT_ALPHA + (255 - BAR_FLAT_ALPHA) * 0.9 * boost)
            else:
                a = BAR_ALPHA
            d.rounded_rectangle(
                (bx, y0, bx + BAR_W * S - S * 0.4, y0 + bh_px),
                BAR_W * S / 2, fill=(255, 255, 255, a))

    # -- cached layers --------------------------------------------------------

    def pill_mask(self, text: str | None):
        """L-mode mask of the pill inside its margin (for X11 shape)."""
        from PIL import Image, ImageDraw
        w, h, radius = self.inner_size(text)
        key = ("mask", w, h, radius)
        cached = self._cache.get(key)
        if cached is None:
            S = 4
            im = Image.new("L", (w * S, h * S), 0)
            ImageDraw.Draw(im).rounded_rectangle(
                (0, 0, w * S - 1, h * S - 1), radius * S, fill=255)
            im = im.resize((w, h), Image.LANCZOS)
            full = Image.new("L", (w + 2 * self.MARGIN, h + 2 * self.MARGIN), 0)
            full.paste(im, (self.MARGIN, self.MARGIN))
            cached = self._cache[key] = full
        return cached

    def _shadow_layer(self, w: int, h: int, radius: int):
        """Soft drop shadow under the pill (cached per size)."""
        from PIL import Image, ImageDraw, ImageFilter
        key = ("shadow", w, h, radius)
        cached = self._cache.get(key)
        if cached is None:
            m = self.MARGIN
            pill = Image.new("L", (w, h), 0)
            ImageDraw.Draw(pill).rounded_rectangle(
                (m, m + 6, w - m - 1, h - m - 1), radius, fill=90)
            pill = pill.filter(ImageFilter.GaussianBlur(7))
            layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            layer.putalpha(pill)
            cached = self._cache[key] = layer
        return cached.copy()


class AudioLevels:
    """Maps recent PCM to per-bar heights: fast attack, slow release."""

    GAIN = 2.4

    def __init__(self, bars: int = BAR_COUNT, lo: float = BAR_MIN_H,
                 hi: float = BAR_MAX_H, rate: int = 16000):
        self.bars = bars
        self.lo = lo
        self.hi = hi
        self.rate = rate
        self._h = [lo] * bars

    def levels(self) -> list[float]:
        return list(self._h)

    def update(self, pcm_tail: bytes | None, chunk_ms: float = 55.0) -> None:
        chunk = int(self.rate * chunk_ms / 1000)  # samples per bar window
        targets = [self.lo] * self.bars
        if pcm_tail:
            need = chunk * self.bars * 2  # s16le mono
            data = pcm_tail[-need:]
            n_chunks = len(data) // (chunk * 2)
            for i in range(n_chunks):
                part = data[i * chunk * 2:(i + 1) * chunk * 2]
                samples = array.array("h")
                samples.frombytes(part)
                rms = math.sqrt(
                    sum(s * s for s in samples) / len(samples)) / 32768.0
                slot = self.bars - n_chunks + i  # newest window -> rightmost bar
                targets[slot] = self.lo + (self.hi - self.lo) * min(
                    1.0, math.sqrt(rms) * self.GAIN)
        for i in range(self.bars):
            t = targets[i]
            self._h[i] = t if t > self._h[i] else \
                self._h[i] * 0.70 + t * 0.30  # ~150 ms release at 30 fps


class FluidOverlay:
    """The pill window. Falls back to NotifyPreview when X11/Pillow fail."""

    FPS = 30

    def __init__(self, display_name: str | None = None,
                 raw_path: Path | None = None,
                 bottom_offset: int = BOTTOM_OFFSET,
                 icon_path: str | Path | None = None):
        from .preview import NotifyPreview
        self.fallback = NotifyPreview()
        self._d = None
        self._win = None
        self._renderer = None
        self._raw_path = raw_path
        self._bottom_offset = bottom_offset
        self._text: str | None = None
        self._state = "recording"
        self._state_since = time.monotonic()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._levels = AudioLevels()
        self._phase = 0.0
        self._last_sig: tuple | None = None
        try:
            self._setup(display_name, icon_path)
        except Exception:
            self._teardown_display()

    # -- X11 plumbing ---------------------------------------------------------

    def _setup(self, display_name: str | None, icon_path) -> None:
        from Xlib import X
        from Xlib.display import Display
        self._X = X
        self._d = Display(display_name)
        self._screen = self._d.screen()
        self._depth, self._visual_id, self._colormap = self._pick_visual()
        self._renderer = PillRenderer(icon_path)
        self._gc = self._scratch_gc()
        self._win_size = (0, 0)

    def _pick_visual(self):
        X = self._X
        screen = self._screen
        # prefer a 32-bit TrueColor visual (compositor -> real alpha)
        for depth in screen.allowed_depths:
            if depth.depth == 32:
                for v in depth.visuals:
                    if v.visual_class == X.TrueColor:
                        cmap = screen.root.create_colormap(v.visual_id,
                                                           X.AllocNone)
                        return 32, v.visual_id, cmap
        return screen.root_depth, None, None

    def _scratch_gc(self):
        pm = self._screen.root.create_pixmap(1, 1, self._depth)
        gc = pm.create_gc(foreground=0, background=0)
        pm.free()
        return gc

    @property
    def using_overlay(self) -> bool:
        return self._d is not None

    # -- lifecycle --------------------------------------------------------------

    def start(self) -> None:
        if self._d is None or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="fluidvoice-overlay",
                                        daemon=True)
        self._thread.start()

    def show(self, text: str) -> None:
        if self._d is None:
            self.fallback.show(text)
            return
        with self._lock:
            self._text = text
            self._last_sig = None  # force redraw + possible resize

    def set_state(self, state: str) -> None:
        """'recording' (bars follow audio) or 'processing' (flat + shimmer)."""
        if self._d is None:
            return  # notifications have no processing visual
        with self._lock:
            self._state = state
            self._state_since = time.monotonic()
            self._last_sig = None

    def close(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2.0)
        self._teardown_display()
        if self.fallback is not None:
            self.fallback.close()

    def _run(self) -> None:
        try:
            interval = 1.0 / self.FPS
            while not self._stop.is_set():
                t0 = time.monotonic()
                state = self._state
                if state == "processing" and \
                        time.monotonic() - self._state_since > PROCESSING_CAP:
                    break
                try:
                    self._tick(state)
                except Exception:
                    break  # display died; future show() goes to notifications
                delay = interval - (time.monotonic() - t0)
                self._stop.wait(max(0.002, delay))
        finally:
            self._teardown_display()

    # -- per-frame ------------------------------------------------------------

    def _tick(self, state: str) -> None:
        X = self._X
        text = self._text
        if state == "recording":
            self._levels.update(self._read_pcm_tail())
        self._phase += 1.0 / self.FPS

        img, (w, h) = self._renderer.render(
            self._levels.levels(), text,
            processing=(state == "processing"), phase=self._phase)
        sig = (w, h, state, text,
               tuple(round(b, 1) for b in self._levels.levels()),
               round(self._phase % SHIMMER_PERIOD, 2))
        if sig == self._last_sig:
            return
        self._last_sig = sig

        if self._win is None or self._win_size != (w, h):
            self._create_window(w, h)

        data = img.tobytes("raw", "BGRA")
        if len(data) > MAX_FRAME_BYTES:
            scale = math.sqrt(MAX_FRAME_BYTES / len(data))
            from PIL import Image
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                             Image.LANCZOS)
            data = img.tobytes("raw", "BGRA")
        self._win.put_image(self._gc, 0, 0, img.width, img.height,
                            X.ZPixmap, self._depth, 0, data)
        if self._depth != 32:
            self._apply_shape(text)
        self._d.flush()

    def _read_pcm_tail(self) -> bytes | None:
        p = self._raw_path
        if p is None:
            return None
        try:
            with open(p, "rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                need = 16000 * 2 * 2  # last ~2 s is plenty for 8 bars
                fh.seek(max(0, size - need))
                return fh.read()
        except OSError:
            return None

    def _create_window(self, w: int, h: int) -> None:
        X = self._X
        screen = self._screen
        if self._win is not None:
            try:
                self._win.unmap()
                self._win.destroy()
                self._d.sync()
            except Exception:
                pass
            self._win = None
        x = (screen.width_in_pixels - w) // 2
        y = screen.height_in_pixels - h - self._bottom_offset
        kwargs = dict(override_redirect=True,
                      event_mask=X.ExposureMask,
                      background_pixel=0,
                      border_pixel=0)
        if self._depth == 32:
            kwargs.update(visual=self._visual_id,
                          colormap=self._colormap)
        self._win = screen.root.create_window(
            max(0, x), max(0, y), w, h, 0, self._depth, **kwargs)
        self._win.map()
        self._d.flush()
        self._win_size = (w, h)
        self._last_sig = None

    def _apply_shape(self, text: str | None) -> None:
        """Opaque fallback: cut the rounded pill out of a rectangular window."""
        try:
            from Xlib.ext import shape as xshape
            mask = self._renderer.pill_mask(text)
            w, h = mask.size
            bm = mask.point(lambda v: 255 if v > 127 else 0).convert("1")
            src_stride = (w + 7) // 8
            dst_stride = (w + 31) // 32 * 4
            raw = bm.tobytes("raw", "1;MSB")
            packed = bytearray(dst_stride * h)
            for yy in range(h):
                row = raw[yy * src_stride:(yy + 1) * src_stride]
                packed[yy * dst_stride:yy * dst_stride + len(row)] = row
            pm = self._screen.root.create_pixmap(w, h, 1)
            pm.put_image(self._gc, 0, 0, w, h, self._X.XYBitmap, 1, 0,
                         bytes(packed))
            self._win.mask(xshape.SO.Set, xshape.SK.Bounding, 0, 0, pm)
            pm.free()
        except Exception:
            pass  # plain rectangle is the last resort; content is still right

    def _teardown_display(self) -> None:
        win, self._win = self._win, None
        d, self._d = self._d, None
        if win is not None and d is not None:
            try:
                win.unmap()
                d.sync()
            except Exception:
                pass
        if d is not None:
            try:
                d.close()
            except Exception:
                pass
