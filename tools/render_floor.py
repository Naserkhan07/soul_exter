"""Rasterise a floor frame (the op list emitted by the renderer) into a PNG.

This is the offline half of the smoke test: the browser and this script consume
the SAME drawing ops, so a frame rendered here is a faithful picture of what
ships — which is the only way to check an isometric scene on a box with no
browser and no GPU.

    python tools/render_floor.py /tmp/floor_frame.json /tmp/floor.png
"""
from __future__ import annotations

import json
import math
import pathlib
import re
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = pathlib.Path("/usr/share/fonts/truetype/dejavu")
FONTS = {
    "sans": FONT_DIR / "DejaVuSans.ttf",
    "sans-bold": FONT_DIR / "DejaVuSans-Bold.ttf",
    "mono": FONT_DIR / "DejaVuSansMono.ttf",
    "mono-bold": FONT_DIR / "DejaVuSansMono-Bold.ttf",
}
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

RGBA_RE = re.compile(r"rgba?\(([^)]+)\)")


def parse_color(value, default=(0, 0, 0, 0)) -> tuple[int, int, int, int]:
    """Accept #rgb, #rrggbb, rgb(), rgba() — the vocabulary the renderer emits."""
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        v = list(value) + [255] * (4 - len(value))
        return (int(v[0]), int(v[1]), int(v[2]), int(v[3]))
    s = str(value).strip()
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) >= 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
        return default
    m = RGBA_RE.match(s)
    if m:
        parts = [p.strip() for p in m.group(1).replace("/", " ").split(",")]
        vals = []
        for p in parts:
            vals.append(float(p[:-1]) / 100.0 if p.endswith("%") else float(p))
        while len(vals) < 4:
            vals.append(255.0 if len(vals) < 3 else 1.0)
        r, g, b, a = vals[0], vals[1], vals[2], vals[3]
        if a <= 1.0:
            a *= 255.0
        return (int(round(r)), int(round(g)), int(round(b)), int(round(a)))
    return default


def font_for(size: int, weight: str = "400", mono: bool = False) -> ImageFont.FreeTypeFont:
    bold = str(weight) in ("bold", "600", "700", "800", "900") or (
        isinstance(weight, (int, float)) and float(weight) >= 600
    )
    key = (("mono" if mono else "sans") + ("-bold" if bold else ""), max(6, int(size)))
    if key in _font_cache:
        return _font_cache[key]
    path = FONTS[key[0]]
    try:
        f = ImageFont.truetype(str(path), key[1])
    except Exception:
        f = ImageFont.load_default(size=key[1])
    _font_cache[key] = f
    return f


class Canvas:
    """A straight-alpha RGBA canvas with the same compositing the browser does."""

    def __init__(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self.buf = np.zeros((h, w, 4), dtype=np.float64)

    # ---- compositing ---------------------------------------------------
    def blend(self, layer: np.ndarray, x0: int, y0: int, alpha: float = 1.0) -> None:
        """Alpha-composite an RGBA float layer (0..255) at (x0, y0)."""
        lh, lw = layer.shape[:2]
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(self.w, x0 + lw)
        y1 = min(self.h, y0 + lh)
        if x1 <= x0 or y1 <= y0:
            return
        sub = layer[y0 - (y0) : y1 - (y0) + (0), :, :]
        # crop the layer to the visible window
        lx0 = x0 - max(0, x0)
        ly0 = y0 - max(0, y0)
        sub = layer[0 : y1 - y0, 0 : x1 - x0, :]
        dst = self.buf[y0:y1, x0:x1]
        sa = (sub[:, :, 3] / 255.0) * alpha
        out_a = sa + dst[:, :, 3] / 255.0 * (1 - sa)
        safe = np.maximum(out_a, 1e-6)
        for c in range(3):
            out_c = (sub[:, :, c] * sa + dst[:, :, c] * (dst[:, :, 3] / 255.0) * (1 - sa)) / safe
            dst[:, :, c] = out_c
        dst[:, :, 3] = out_a * 255.0

    def image(self) -> Image.Image:
        arr = np.clip(self.buf, 0, 255).astype(np.uint8)
        return Image.fromarray(arr, "RGBA")


# ---------------------------------------------------------------------------
# gradients
# ---------------------------------------------------------------------------
def _stops_colors(stops, n: int) -> np.ndarray:
    """Sample a stop list into n RGB (+alpha) values."""
    ss = sorted(((float(t), parse_color(c)) for t, c in stops), key=lambda kv: kv[0])
    if not ss:
        return np.zeros((n, 4), dtype=np.float64)
    if len(ss) == 1:
        return np.tile(np.array(ss[0][1], dtype=np.float64), (n, 1))
    xs = np.linspace(0.0, 1.0, n)
    ts = np.array([s[0] for s in ss])
    cols = np.array([s[1] for s in ss], dtype=np.float64)
    out = np.zeros((n, 4), dtype=np.float64)
    for c in range(4):
        out[:, c] = np.interp(xs, ts, cols[:, c])
    return out


def linear_gradient(w: int, h: int, p0, p1, stops) -> np.ndarray:
    """Linear gradient across a w x h box, projected on the p0->p1 axis."""
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    denom = dx * dx + dy * dy
    yy, xx = np.mgrid[0:h, 0:w]
    if denom <= 1e-9:
        t = np.zeros((h, w))
    else:
        t = ((xx - p0[0]) * dx + (yy - p0[1]) * dy) / denom
    t = np.clip(t, 0.0, 1.0).ravel()
    cols = _stops_colors(stops, 512)
    idx = np.clip((t * 511).astype(np.int32), 0, 511)
    rgba = cols[idx].reshape(h, w, 4)
    return rgba


def radial_gradient(w: int, h: int, centre, radius: float, stops) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot(xx - centre[0], yy - centre[1]) / max(1e-6, radius)
    t = np.clip(r, 0.0, 1.0).ravel()
    cols = _stops_colors(stops, 512)
    idx = np.clip((t * 511).astype(np.int32), 0, 511)
    return cols[idx].reshape(h, w, 4)


# ---------------------------------------------------------------------------
# op rendering
# ---------------------------------------------------------------------------
def fill_mask(size, draw_fn) -> np.ndarray:
    """A soft-edged coverage mask (0..255) built with Pillow's anti-aliasing."""
    scale = 2  # supersample for smoother edges than Pillow's default
    w, h = size[0] * scale, size[1] * scale
    if w <= 0 or h <= 0:
        return np.zeros((max(1, size[1]), max(1, size[0])), dtype=np.float64)
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    draw_fn(d, scale)
    if scale != 1:
        img = img.resize(size, Image.LANCZOS)
    return np.asarray(img, dtype=np.float64)


def bbox_of(points) -> tuple[int, int, int, int]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0 = int(math.floor(min(xs))) - 2
    y0 = int(math.floor(min(ys))) - 2
    x1 = int(math.ceil(max(xs))) + 2
    y1 = int(math.ceil(max(ys))) + 2
    return x0, y0, max(1, x1 - x0), max(1, y1 - y0)


def render_op(canvas: Canvas, op: dict) -> None:
    kind = op.get("op")
    alpha = float(op.get("alpha", 1.0))
    if alpha <= 0.004:
        return

    if kind == "poly":
        pts = [(float(x), float(y)) for x, y in op["pts"]]
        if len(pts) < 3:
            return
        x0, y0, w, h = bbox_of(pts)
        local = [(x - x0, y - y0) for x, y in pts]

        def draw_poly(d, s):
            d.polygon([(x * s, y * s) for x, y in local], fill=255)

        mask = fill_mask((w, h), draw_poly)
        if op.get("grad"):
            g = op["grad"]
            if g.get("radial"):
                c = (g["from"][0] - x0, g["from"][1] - y0)
                r = math.hypot(g["to"][0] - g["from"][0], g["to"][1] - g["from"][1]) or 1.0
                layer = radial_gradient(w, h, c, r, g["stops"])
            else:
                p0 = (g["from"][0] - x0, g["from"][1] - y0)
                p1 = (g["to"][0] - x0, g["to"][1] - y0)
                layer = linear_gradient(w, h, p0, p1, g["stops"])
        else:
            col = np.array(parse_color(op.get("fill")), dtype=np.float64)
            layer = np.zeros((h, w, 4), dtype=np.float64)
            layer[:, :, 0], layer[:, :, 1], layer[:, :, 2], layer[:, :, 3] = col
        layer[:, :, 3] *= mask / 255.0
        canvas.blend(layer, x0, y0, alpha)

        if op.get("stroke") and float(op.get("lw", 0)) > 0:
            stroke = parse_color(op["stroke"])
            lw = float(op["lw"])
            x0, y0, w, h = bbox_of(pts)

            def draw_outline(d, s):
                d.line([(x * s, y * s) for x, y in local] + [(local[0][0] * s, local[0][1] * s)],
                       fill=255, width=max(1, int(round(lw * s))), joint="curve")

            mask = fill_mask((w, h), draw_outline)
            layer = np.zeros((h, w, 4), dtype=np.float64)
            layer[:, :, 0], layer[:, :, 1], layer[:, :, 2], layer[:, :, 3] = stroke
            layer[:, :, 3] *= mask / 255.0
            canvas.blend(layer, x0, y0, alpha)

    elif kind == "ellipse":
        cx, cy = float(op["cx"]), float(op["cy"])
        rx, ry = max(0.2, float(op["rx"])), max(0.2, float(op["ry"]))
        x0, y0 = int(cx - rx) - 2, int(cy - ry) - 2
        w, h = int(rx * 2) + 5, int(ry * 2) + 5
        local_c = (cx - x0, cy - y0)

        def draw_ellipse(d, s):
            d.ellipse(
                [(local_c[0] - rx) * s, (local_c[1] - ry) * s,
                 (local_c[0] + rx) * s, (local_c[1] + ry) * s],
                fill=255,
            )

        mask = fill_mask((w, h), draw_ellipse)
        if op.get("grad"):
            g = op["grad"]
            if g.get("radial"):
                c = (g["from"][0] - x0, g["from"][1] - y0)
                r = math.hypot(g["to"][0] - g["from"][0], g["to"][1] - g["from"][1]) or 1.0
                layer = radial_gradient(w, h, c, r, g["stops"])
            else:
                layer = linear_gradient(
                    w, h, (g["from"][0] - x0, g["from"][1] - y0),
                    (g["to"][0] - x0, g["to"][1] - y0), g["stops"])
        else:
            col = np.array(parse_color(op.get("fill")), dtype=np.float64)
            layer = np.zeros((h, w, 4), dtype=np.float64)
            layer[:, :, :3] = col[:3]
            layer[:, :, 3] = col[3]
        layer[:, :, 3] *= mask / 255.0
        canvas.blend(layer, x0, y0, alpha)

    elif kind == "line":
        pts = [(float(x), float(y)) for x, y in op["pts"]]
        if len(pts) < 2:
            return
        lw = max(1.0, float(op.get("lw", 1.0)))
        col = parse_color(op.get("stroke"))
        x0, y0, w, h = bbox_of([(x - lw, y - lw) for x, y in pts] + [(x + lw, y + lw) for x, y in pts])
        local = [(x - x0, y - y0) for x, y in pts]

        def draw_line(d, s):
            d.line([(x * s, y * s) for x, y in local], fill=255,
                   width=max(1, int(round(lw * s))), joint="curve")
            r = lw / 2.0
            for x, y in local:  # round caps
                d.ellipse([(x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s], fill=255)

        mask = fill_mask((w, h), draw_line)
        layer = np.zeros((h, w, 4), dtype=np.float64)
        layer[:, :, 0], layer[:, :, 1], layer[:, :, 2], layer[:, :, 3] = col
        layer[:, :, 3] *= mask / 255.0
        canvas.blend(layer, x0, y0, alpha)

    elif kind == "round":
        x, y = float(op["x"]), float(op["y"])
        w, h = max(1.0, float(op["w"])), max(1.0, float(op["h"]))
        r = float(op.get("r", 0))
        x0, y0 = int(x) - 2, int(y) - 2
        ww, hh = int(w) + 5, int(h) + 5
        lx, ly = x - x0, y - y0

        def draw_round(d, s):
            d.rounded_rectangle([lx * s, ly * s, (lx + w) * s, (ly + h) * s],
                                radius=max(0.0, r * s), fill=255)

        mask = fill_mask((ww, hh), draw_round)
        if op.get("grad"):
            g = op["grad"]
            if g.get("radial"):
                c = (g["from"][0] - x0, g["from"][1] - y0)
                rad = math.hypot(g["to"][0] - g["from"][0], g["to"][1] - g["from"][1]) or 1.0
                layer = radial_gradient(ww, hh, c, rad, g["stops"])
            else:
                layer = linear_gradient(
                    ww, hh, (g["from"][0] - x0, g["from"][1] - y0),
                    (g["to"][0] - x0, g["to"][1] - y0), g["stops"])
        else:
            col = np.array(parse_color(op.get("fill")), dtype=np.float64)
            layer = np.zeros((hh, ww, 4), dtype=np.float64)
            layer[:, :, 0], layer[:, :, 1], layer[:, :, 2], layer[:, :, 3] = col
        layer[:, :, 3] *= mask / 255.0
        canvas.blend(layer, x0, y0, alpha)

    elif kind == "text":
        size = max(6, int(round(float(op.get("size", 12)))))
        f = font_for(size, str(op.get("weight", "400")), bool(op.get("mono")))
        col = parse_color(op.get("fill"))
        text = str(op.get("text", ""))
        if not text:
            return
        left, top, right, bottom = f.getbbox(text)
        tw = right - left
        th = bottom - top
        pad = 4
        x = float(op["x"])
        y = float(op["y"])
        align = op.get("align", "left")
        if align == "center":
            x -= tw / 2
        elif align == "right":
            x -= tw
        x0 = int(x) - pad
        y0 = int(y) - th - pad
        w, h = tw + pad * 2 + 2, th + pad * 2 + 2
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((pad - left, pad - top), text, font=f, fill=col)
        layer = np.asarray(img, dtype=np.float64)
        canvas.blend(layer, x0, y0, alpha)

    elif kind == "clip" or kind == "restore":
        # The offline view has no nested viewports; clipping is a browser-only
        # nicety here (nothing in the shipped scene relies on it for correctness).
        return


def render(frame: dict, out_path: str) -> dict:
    w, h = frame.get("size", [1280, 800])
    canvas = Canvas(int(w), int(h))
    counts: dict[str, int] = {}
    for op in frame.get("ops", []):
        counts[op.get("op", "?")] = counts.get(op.get("op", "?"), 0) + 1
        render_op(canvas, op)
    img = canvas.image()
    # flatten onto the darkest room colour so the PNG is not transparent
    bg = Image.new("RGBA", img.size, parse_color("#05070c"))
    flat = Image.alpha_composite(bg, img).convert("RGB")
    pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    flat.save(out_path)
    return {"out": out_path, "size": [w, h], "ops": len(frame.get("ops", [])), "by_op": counts}


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    frame = json.loads(pathlib.Path(sys.argv[1]).read_text())
    info = render(frame, sys.argv[2])
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
