#!/usr/bin/env python3
"""
Turn a flat-colour logo image into the site's brand assets.

Logo files tend to arrive as JPEGs with a baked-in white background, generous
margins and compression ringing around every edge. This script cleans that up
and writes everything the templates expect:

    templates/partials/logo.html   inline SVG for the header (currentColor)
    static/img/logo.svg            same geometry, fixed fill, SVG favicon
    static/img/logo.png            512px transparent master
    static/img/icon-16/32/180.png  favicon set

Two details that matter:

*   The alpha is *unmixed*, not colour-keyed. Every pixel is a blend of the
    mark colour over the background, so solving that per pixel recovers real
    anti-aliased edges and makes JPEG ringing fade to zero alpha instead of
    leaving a halo.
*   If the mark decomposes into axis-aligned rectangles, it is re-emitted as
    exact vector geometry, which beats any resampling of the original. Marks
    with curves fall back to raster assets only.

    .venv/bin/python scripts/make_logo.py <image> [--accent '#6c8cff']
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PROJECT = Path(__file__).resolve().parent.parent
BOX, MARGIN = 24.0, 1.5          # SVG viewBox and its inner padding
PNG_MARGIN = 1.14                # square canvas relative to the mark


def hex_to_rgb(value):
    value = value.lstrip("#")
    return np.array([int(value[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


def unmix_alpha(pixels, mark, background):
    """Recover per-pixel coverage of `mark` painted over `background`."""
    gap = background - mark
    useful = np.abs(gap) > 30
    if not useful.any():
        sys.exit("error: the mark colour is too close to the background to separate.")
    alpha = ((background - pixels)[..., useful] / gap[useful]).mean(axis=2)
    return np.clip(alpha, 0.0, 1.0)


# A band counts as a rectangle at or above this fill ratio. Not 100%: a JPEG
# source leaves single-pixel ringing along the edges. A genuinely curved shape
# fills only about 78% of its bounding box, so the two stay well separated.
RECT_FILL = 0.99


def find_rectangles(solid):
    """Split the mask into horizontal bands; return them if each is a rectangle."""
    rows = np.nonzero(solid.any(axis=1))[0]
    if not len(rows):
        sys.exit("error: no mark found — is the image blank?")

    bands, start = [], rows[0]
    for previous, current in zip(rows, rows[1:]):
        if current != previous + 1:
            bands.append((start, previous))
            start = current
    bands.append((start, rows[-1]))

    rects = []
    for y0, y1 in bands:
        columns = np.nonzero(solid[y0:y1 + 1].any(axis=0))[0]
        x0, x1 = int(columns.min()), int(columns.max()) + 1
        fill = solid[y0:y1 + 1, x0:x1].mean()
        print(f"  band {x1 - x0}x{y1 - y0 + 1}px fills {100 * fill:.2f}% of its box")
        if fill < RECT_FILL:
            return None
        rects.append((x0, int(y0), x1, int(y1) + 1))
    return rects


def main():
    parser = argparse.ArgumentParser(description="Build the brand assets from a logo image.")
    parser.add_argument("source")
    parser.add_argument("--accent", default="#6c8cff", help="colour the assets are emitted in")
    parser.add_argument("--background", default="#ffffff", help="colour to remove")
    args = parser.parse_args()

    image = Image.open(args.source).convert("RGB")
    pixels = np.asarray(image).astype(np.float32)
    print(f"source: {args.source} — {image.size[0]}x{image.size[1]}")

    background = hex_to_rgb(args.background)
    # The most common non-background colour is the mark.
    flat = pixels.reshape(-1, 3)
    colours, counts = np.unique(flat.astype(np.uint8), axis=0, return_counts=True)
    far = np.linalg.norm(colours.astype(np.float32) - background, axis=1) > 40
    mark = colours[far][np.argmax(counts[far])].astype(np.float32)
    print(f"detected mark colour: #{int(mark[0]):02x}{int(mark[1]):02x}{int(mark[2]):02x}"
          f"  -> emitting as {args.accent}")

    alpha = unmix_alpha(pixels, mark, background)
    solid = alpha > 0.5
    ys, xs = np.nonzero(solid)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    print(f"mark bounds: {x1 - x0}x{y1 - y0}px, {100 * solid.mean():.1f}% of the canvas")

    # ---- vector, when the shape allows it ----
    rects = find_rectangles(solid)
    if rects:
        print(f"shape is {len(rects)} axis-aligned rectangle(s) — emitting exact vector")
        width, height = x1 - x0, y1 - y0
        scale = min((BOX - 2 * MARGIN) / width, (BOX - 2 * MARGIN) / height)
        off_x = (BOX - width * scale) / 2
        off_y = (BOX - height * scale) / 2
        body = "\n".join(
            f'  <rect x="{round((r[0] - x0) * scale + off_x, 3)}" '
            f'y="{round((r[1] - y0) * scale + off_y, 3)}" '
            f'width="{round((r[2] - r[0]) * scale, 3)}" '
            f'height="{round((r[3] - r[1]) * scale, 3)}" rx="0.35"/>'
            for r in rects
        )

        (PROJECT / "templates/partials/logo.html").write_text(
            "{% comment %}\n"
            "The brand mark. Generated by scripts/make_logo.py — do not hand-edit.\n"
            "Inline rather than an <img> so fill=\"currentColor\" picks up the CSS\n"
            "accent colour; an <img> has no CSS context and would render it black.\n"
            "{% endcomment %}\n"
            '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">\n'
            + body + "\n</svg>\n", encoding="utf-8")

        (PROJECT / "static/img/logo.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{args.accent}">\n'
            + body + "\n</svg>\n", encoding="utf-8")
        print("  wrote templates/partials/logo.html and static/img/logo.svg")
    else:
        print("shape has curves — keeping the existing SVG, writing raster assets only")

    # ---- raster ----
    rgba = np.zeros(pixels.shape[:2] + (4,), np.uint8)
    rgba[..., :3] = hex_to_rgb(args.accent).astype(np.uint8)
    rgba[..., 3] = (alpha * 255).round().astype(np.uint8)
    master = Image.fromarray(rgba, "RGBA").crop((x0, y0, x1, y1))

    side = int(max(master.size) * PNG_MARGIN)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(master, ((side - master.width) // 2, (side - master.height) // 2))

    out = PROJECT / "static/img"
    out.mkdir(parents=True, exist_ok=True)
    square.resize((512, 512), Image.LANCZOS).save(out / "logo.png")
    for size in (16, 32):
        square.resize((size, size), Image.LANCZOS).save(out / f"icon-{size}.png")

    # iOS ignores transparency, so the touch icon gets an opaque tile.
    tile = Image.new("RGBA", (180, 180), (18, 18, 26, 255))
    tile.alpha_composite(square.resize((180, 180), Image.LANCZOS))
    tile.convert("RGB").save(out / "icon-180.png")
    print("  wrote logo.png (512) and icon-16/32/180.png")

    print("\nnow run:  manage.py collectstatic --noinput  &&  systemctl restart photo-frame-2d")


if __name__ == "__main__":
    main()
