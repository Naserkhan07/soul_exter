"""Rasterise one captured floor frame to a PNG.

`tools/floor_smoke.mjs` records every canvas draw call from web/floor.js against
a stubbed context; this replays those calls through Pillow so the floor layout
can be reviewed without a browser.

Canvas semantics that matter here:
  * an RGBA fill *replaces* pixels in Pillow's "RGB" draw modes, so anything
    semi-transparent is composited through a small temporary tile instead
  * gradients are flattened to one representative colour (see _gradient_color)

    node tools/floor_smoke.mjs /tmp/floor.json
    python tools/render_floor.py /tmp/floor.json floor.png
"""
from __future__ import annotations

import json
import re
import sys

from PIL import Image, ImageDraw, ImageFont

BG = (7, 10, 15, 255)


# ── colour helpers ───────────────────────────────────────────────────────
def _gradient_color(g):
    """Flatten a canvas gradient to one colour.

    Stop 0 is the right pick for everything web/floor.js draws: the floor
    gradient starts at its brightest, the spotlight pools start bright, and the
    vignette starts fully transparent (which we read as "do not paint").
    """
    stops = g.get("stops") or []
    if not stops:
        return None
    first = parse_color(stops[0][1])
    if first is None:
        return None
    if first[3] == 0:
        # a gradient that begins transparent is a soft light/edge effect:
        # flatten it to a low-alpha version of its strongest stop
        best = None
        for _, c in stops:
            col = parse_color(c)
            if col and (best is None or col[3] > best[3]):
                best = col
        if best is None:
            return None
        return (best[0], best[1], best[2], min(best[3], 46))
    return first


def parse_color(c):
    if isinstance(c, dict):
        return _gradient_color(c)
    if not c or c == "transparent":
        return None
    if not isinstance(c, str):
        return None
    if c.startswith("rgba") or c.startswith("rgb"):
        nums = [float(x) for x in re.findall(r"[-.\d]+", c)]
        if len(nums) >= 4:
            return (int(nums[0]), int(nums[1]), int(nums[2]), int(255 * nums[3]))
        if len(nums) >= 3:
            return (int(nums[0]), int(nums[1]), int(nums[2]), 255)
        return None
    if c.startswith("#"):
        h = c[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
    return None


_FONTS: dict[int, ImageFont.FreeTypeFont] = {}


def font(size):
    key = max(7, int(size))
    if key in _FONTS:
        return _FONTS[key]
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            _FONTS[key] = ImageFont.truetype(path, key)
            return _FONTS[key]
        except Exception:
            continue
    _FONTS[key] = ImageFont.load_default()
    return _FONTS[key]


def with_alpha(col, alpha):
    if col is None or alpha >= 1:
        return col
    return (col[0], col[1], col[2], int(col[3] * alpha))


def bbox_of(op):
    kind = op["op"]
    if kind == "poly":
        pts = [p for p in op.get("pts", []) if p]
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        pad = 3 + op.get("lw", 1)
        return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    if kind == "rect":
        return (op["x"] - 2, op["y"] - 2, op["x"] + op["w"] + 2, op["y"] + op["h"] + 2)
    if kind == "ellipse":
        return (op["x"] - op["rx"] - 2, op["y"] - op["ry"] - 2, op["x"] + op["rx"] + 2, op["y"] + op["ry"] + 2)
    if kind == "text":
        size = op.get("size", 10)
        w = max(20, len(str(op.get("t", ""))) * size * 0.62)
        return (op["x"] - w, op["y"] - size, op["x"] + w, op["y"] + size)
    return None


def paint(d, op, ox, oy, fill, stroke, alpha):
    """Draw one op into an ImageDraw, offset by (ox, oy) for tile rendering."""
    kind = op["op"]
    if kind == "poly":
        pts = [(p[0] - ox, p[1] - oy) for p in op.get("pts", []) if p]
        if len(pts) < 2:
            return
        if fill and len(pts) > 2:
            d.polygon(pts, fill=fill)
        if stroke:
            d.line(pts + [pts[0]] if len(pts) > 2 else pts, fill=stroke,
                   width=max(1, int(op.get("lw", 1))), joint="curve")
    elif kind == "rect":
        d.rectangle([op["x"] - ox, op["y"] - oy, op["x"] + op["w"] - ox, op["y"] + op["h"] - oy], fill=fill)
    elif kind == "ellipse":
        box = [op["x"] - op["rx"] - ox, op["y"] - op["ry"] - oy,
               op["x"] + op["rx"] - ox, op["y"] + op["ry"] - oy]
        if fill:
            d.ellipse(box, fill=fill)
        if stroke:
            d.ellipse(box, outline=stroke, width=max(1, int(op.get("lw", 1))))
    elif kind == "text":
        t = str(op.get("t", ""))
        if not t:
            return
        col = fill or (232, 238, 246, 255)
        f = font(op.get("size", 10))
        try:
            w = d.textlength(t, font=f)
        except Exception:
            w = len(t) * 6
        d.text((op["x"] - w / 2 - ox, op["y"] - op.get("size", 10) / 2 - oy), t, font=f, fill=col)


def main(src: str, dst: str) -> int:
    data = json.load(open(src))
    W, H = data["w"], data["h"]
    ops = data["ops"]
    img = Image.new("RGBA", (W, H), BG)
    tile_cache: dict = {}
    drawn = 0

    for op in ops:
        alpha = op.get("alpha", 1) or 1
        fill = with_alpha(parse_color(op.get("fill")), alpha)
        stroke = with_alpha(parse_color(op.get("stroke")), alpha)
        if op["op"] == "text":
            fill = with_alpha(parse_color(op.get("fill")) or (232, 238, 246, 255), alpha)
        if fill is None and stroke is None:
            continue

        opaque = ((fill is None or fill[3] >= 255) and (stroke is None or stroke[3] >= 255))
        if opaque:
            paint(ImageDraw.Draw(img, "RGBA"), op, 0, 0, fill, stroke, alpha)
            drawn += 1
            continue

        # semi-transparent: render into a tile and composite it properly
        box = bbox_of(op)
        if box is None:
            continue
        if op["op"] == "rect" and (box[2] - box[0] > W * 0.9):
            # a full-canvas wash (the vignette): apply it across the frame
            g = op.get("fill")
            base_alpha = _gradient_color(g)
            if base_alpha is None or base_alpha[3] == 0:
                continue
            shade = Image.new("RGBA", (W, H), (base_alpha[0], base_alpha[1], base_alpha[2],
                                               int(base_alpha[3] * 0.55)))
            img.alpha_composite(shade)
            drawn += 1
            continue
        x0 = max(0, int(box[0])); y0 = max(0, int(box[1]))
        x1 = min(W, int(box[2]) + 1); y1 = min(H, int(box[3]) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        tile = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
        paint(ImageDraw.Draw(tile, "RGBA"), op, x0, y0, fill, stroke, alpha)
        img.alpha_composite(tile, (x0, y0))
        drawn += 1

    img.convert("RGB").save(dst, quality=92)
    print(f"ops={len(ops)} drawn={drawn} -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/floor.json",
                  sys.argv[2] if len(sys.argv) > 2 else "floor.png"))
