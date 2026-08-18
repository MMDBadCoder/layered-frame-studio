"""
Verification of ready-made images.

Some customers already have a layered image made elsewhere (an AI model, a
graphics editor). We accept those directly, but only after checking the image
really is built from a small set of solid colours — otherwise the workshop
cannot cut it and the 3D export would be meaningless.

The check is deliberately tolerant of compression noise: a PNG exported with
four flat colours has exactly four colours, but the same picture saved as JPEG
has thousands of near-duplicates around every edge. So instead of counting
exact colours we cluster them and measure how much of the picture those
clusters actually cover.

Only numpy and Pillow are used.
"""

import io

import numpy as np
from PIL import Image

from .jalali import to_persian_digits

# Pixels within this RGB distance of a cluster centre count as that colour.
# Comfortably absorbs JPEG ringing without merging genuinely distinct layers.
DEFAULT_TOLERANCE = 18

# A cluster covering less than this share of the image is not a layer: it is
# compression ringing along an edge. Such clusters are folded into the nearest
# real layer. A frame layer below ~1% of the area is not producible anyway.
MIN_LAYER_SHARE = 0.01  # 1%

# Analysis runs on a downscaled copy; the palette of a flat image does not
# change with resolution, and this keeps verification fast for big uploads.
ANALYSIS_MAX_SIDE = 700

# Clustering budget. We deliberately look for far more clusters than the layer
# limit: anti-aliased or JPEG-compressed edges produce a long tail of tiny
# clusters, and we want to see and absorb them rather than fail on their count.
CLUSTER_BUDGET_FACTOR = 3
CLUSTER_BUDGET_MIN = 24
CLUSTER_BUDGET_MAX = 64


def rgb_to_hex(color) -> str:
    return "#{:02x}{:02x}{:02x}".format(int(color[0]), int(color[1]), int(color[2]))


def _load_rgb(image_bytes: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(image_bytes))
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image


def _downscale(image: Image.Image, max_side: int = ANALYSIS_MAX_SIDE) -> Image.Image:
    longest = max(image.size)
    if longest <= max_side:
        return image
    scale = max_side / longest
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    # NEAREST keeps flat regions flat instead of inventing blend colours.
    return image.resize(size, Image.NEAREST)


def detect_palette(pixels: np.ndarray, max_colors: int, tolerance: int = DEFAULT_TOLERANCE):
    """
    Greedily cluster pixels around their most frequent colours.

    Repeatedly takes the most common remaining colour as a cluster centre and
    claims every pixel within `tolerance` of it. Stops once everything is
    claimed or more than `max_colors` clusters are needed.

    Returns (clusters, covered_fraction) where clusters is a list of
    (rgb_tuple, pixel_count) ordered by size, largest first.
    """
    # int32 is required: squared channel differences reach 65025, which
    # overflows int16 and would make far-apart colours look adjacent.
    flat = pixels.reshape(-1, 3).astype(np.int32)
    total = len(flat)
    if total == 0:
        return [], 0.0

    unclaimed = np.ones(total, dtype=bool)
    clusters = []
    tolerance_sq = tolerance * tolerance

    # One extra pass so we can tell "exactly at the limit" from "over the limit".
    while unclaimed.any() and len(clusters) <= max_colors:
        remaining = flat[unclaimed]

        # Most frequent exact colour among what is left.
        packed = (
            remaining[:, 0].astype(np.uint32) << 16
            | remaining[:, 1].astype(np.uint32) << 8
            | remaining[:, 2].astype(np.uint32)
        )
        values, counts = np.unique(packed, return_counts=True)
        winner = int(values[np.argmax(counts)])
        centre = np.array([(winner >> 16) & 255, (winner >> 8) & 255, winner & 255], dtype=np.int32)

        distances = np.sum((flat - centre) ** 2, axis=1)
        claimed = unclaimed & (distances <= tolerance_sq)
        count = int(claimed.sum())
        if count == 0:  # pragma: no cover - defensive, centre always claims itself
            break

        clusters.append((tuple(int(v) for v in centre), count))
        unclaimed &= ~claimed

    covered = 1.0 - float(unclaimed.sum()) / total
    clusters.sort(key=lambda item: item[1], reverse=True)
    return clusters, covered


def merge_minor_clusters(clusters, total: int, min_share: float):
    """
    Fold sub-threshold clusters into the nearest real layer.

    Saving a four-colour picture as JPEG scatters blend colours along every
    edge. Those form their own small clusters, and without this pass a clean
    four-layer design would be reported as six layers — and would be built with
    two bogus wafer-thin terraces.

    Returns clusters with the absorbed pixel counts added back in.
    """
    layers = [entry for entry in clusters if entry[1] / total >= min_share]
    minor = [entry for entry in clusters if entry[1] / total < min_share]

    if not layers:
        return clusters

    counts = {colour: count for colour, count in layers}
    for colour, count in minor:
        nearest = min(
            counts,
            key=lambda centre: sum((a - b) ** 2 for a, b in zip(centre, colour)),
        )
        counts[nearest] += count

    merged = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return merged


def order_palette_by_luminance(clusters):
    """Darkest first, matching how colour profiles number their layers."""
    def luminance(entry):
        r, g, b = entry[0]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    return sorted(clusters, key=luminance)


def snap_to_palette(image: Image.Image, palette) -> bytes:
    """
    Rewrite the image so it contains only the palette colours.

    Compression noise around edges is pulled onto the nearest layer, which is
    what makes the stored order image safe to feed to the STL exporter.
    """
    pixels = np.asarray(image, dtype=np.int32)
    centres = np.array(palette, dtype=np.int32)

    distances = np.sum((pixels[:, :, None, :] - centres[None, None, :, :]) ** 2, axis=3)
    nearest = np.argmin(distances, axis=2)
    snapped = centres[nearest].astype(np.uint8)

    out = io.BytesIO()
    Image.fromarray(snapped, mode="RGB").save(out, format="PNG")
    return out.getvalue()


def verify_ready_image(
    image_bytes: bytes,
    max_colors: int = 16,
    min_coverage: float = 99.0,
    tolerance: int = DEFAULT_TOLERANCE,
    min_layer_share: float = MIN_LAYER_SHARE,
) -> dict:
    """
    Decide whether an uploaded image is a usable layered image.

    Returns a dict with:
        ok             bool
        colors         list of hex strings, darkest first (when ok)
        shares         matching list of percentages
        color_count    how many layers were found
        coverage       percentage of the image the palette accounts for
        reason         machine-readable failure code (when not ok)
        message        Persian explanation for the user
    """
    image = _load_rgb(image_bytes)
    sample = _downscale(image)
    pixels = np.asarray(sample, dtype=np.uint8)
    total = pixels.shape[0] * pixels.shape[1]

    budget = min(CLUSTER_BUDGET_MAX, max(CLUSTER_BUDGET_MIN, max_colors * CLUSTER_BUDGET_FACTOR))
    clusters, covered = detect_palette(pixels, budget, tolerance)
    coverage_percent = round(covered * 100, 2)

    # Fold edge artefacts into the layers they belong to, THEN judge how many
    # layers there really are. Counting raw clusters would reject a clean
    # four-colour design just for having soft edges.
    significant = merge_minor_clusters(clusters, total, min_layer_share)

    exact_colors = len(np.unique(pixels.reshape(-1, 3), axis=0))

    if len(significant) > max_colors:
        return {
            "ok": False,
            "reason": "too_many_colors",
            "color_count": len(significant),
            "exact_colors": int(exact_colors),
            "coverage": coverage_percent,
            "message": (
                "این تصویر از رنگ‌های یکدست ساخته نشده است. "
                f"حداکثر {to_persian_digits(max_colors)} رنگ مجاز است، "
                "اما تصویر شما رنگ‌های بسیار بیشتری دارد."
            ),
        }

    if coverage_percent < min_coverage:
        return {
            "ok": False,
            "reason": "low_coverage",
            "color_count": len(significant),
            "exact_colors": int(exact_colors),
            "coverage": coverage_percent,
            "message": (
                "رنگ‌های این تصویر یکدست نیستند (طیف یا سایه دارد). "
                f"تنها {to_persian_digits(coverage_percent)}٪ تصویر با رنگ‌های اصلی پوشش داده شد."
            ),
        }

    if len(significant) < 2:
        return {
            "ok": False,
            "reason": "too_few_colors",
            "color_count": len(significant),
            "exact_colors": int(exact_colors),
            "coverage": coverage_percent,
            "message": "این تصویر تقریباً تک‌رنگ است و لایه‌ای برای ساخت ندارد.",
        }

    ordered = order_palette_by_luminance(significant)
    claimed = sum(count for _, count in significant)

    return {
        "ok": True,
        "colors": [rgb_to_hex(color) for color, _ in ordered],
        "rgb": [color for color, _ in ordered],
        "shares": [round(count / claimed * 100, 1) for _, count in ordered],
        "color_count": len(ordered),
        "exact_colors": int(exact_colors),
        "coverage": coverage_percent,
        "message": f"تصویر تأیید شد: {to_persian_digits(len(ordered))} رنگ یکدست شناسایی شد.",
    }


def prepare_ready_image(image_bytes: bytes, palette_rgb) -> bytes:
    """Full-resolution PNG containing only the verified palette colours."""
    return snap_to_palette(_load_rgb(image_bytes), palette_rgb)
