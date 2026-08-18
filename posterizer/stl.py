"""
Turn a layered order image into a printable 3D plate (binary STL).

Each colour of the palette becomes a terrace at its own height, so the result
is a relief plate: flat rectangular footprint, stepped top surface.

The mesh is built to be watertight and manifold — every edge is shared by
exactly two triangles — which is what slicers need. `mesh_is_closed()` checks
that property and is exercised by the test suite.

Only numpy and Pillow are used; no CAD dependency.
"""

import io
import struct
from collections import Counter

import numpy as np
from PIL import Image

# A sane ceiling: beyond this the STL gets unwieldy for very little gain.
MAX_CELLS = 2_000_000


def hex_to_rgb(value: str) -> tuple:
    value = str(value).strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def layer_index_map(image: Image.Image, colors, max_resolution: int) -> np.ndarray:
    """
    Downsample the image and map every pixel to the palette index it matches.

    Nearest-neighbour resizing is deliberate: interpolation would invent
    in-between colours that do not belong to any layer.
    """
    width, height = image.size
    longest = max(width, height)

    if longest > max_resolution:
        scale = max_resolution / longest
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = image.resize(new_size, Image.NEAREST)

    # int32, not int16: a squared channel difference reaches 255**2 = 65025,
    # which overflows int16 and makes argmin pick the wrong colour entirely.
    pixels = np.asarray(image.convert("RGB"), dtype=np.int32)
    palette = np.array([hex_to_rgb(color) for color in colors], dtype=np.int32)

    # Nearest palette entry per pixel, so a stray colour still lands on a layer.
    distances = np.sum((pixels[:, :, None, :] - palette[None, None, :, :]) ** 2, axis=3)
    return np.argmin(distances, axis=2).astype(np.int32)


def resolve_saddles(indices: np.ndarray, max_passes: int = 32) -> tuple:
    """
    Remove saddle points from the layer map.

    In a 2x2 block

        A B
        C D

    trouble happens when one diagonal sits strictly above the other — say both
    B and C are taller than both A and D. Slice the solid anywhere between the
    two diagonals and the cross-section is two squares meeting at a single
    corner, so the plate is pinched to a line there: a non-manifold edge no
    printer can produce.

    The fix raises the lower diagonal's corner until the diagonals overlap,
    which fills the pinch instead of leaving a hairline join. Only raising is
    ever done, so the loop is monotone and always terminates.

    Returns (fixed_indices, number_of_cells_changed).
    """
    fixed = indices.copy()
    changed = 0

    for _ in range(max_passes):
        top_left = fixed[:-1, :-1]
        top_right = fixed[:-1, 1:]
        bottom_left = fixed[1:, :-1]
        bottom_right = fixed[1:, 1:]

        main_low = np.minimum(top_left, bottom_right)
        main_high = np.maximum(top_left, bottom_right)
        anti_low = np.minimum(top_right, bottom_left)
        anti_high = np.maximum(top_right, bottom_left)

        anti_above = anti_low > main_high   # B/C tower over A/D
        main_above = main_low > anti_high   # A/D tower over B/C

        if not (anti_above.any() or main_above.any()):
            break

        rows, cols = np.nonzero(anti_above)
        fixed[rows + 1, cols + 1] = anti_low[rows, cols]
        changed += len(rows)

        rows, cols = np.nonzero(main_above)
        fixed[rows + 1, cols] = main_low[rows, cols]
        changed += len(rows)

    return fixed, changed


class MeshBuilder:
    """Collects axis-aligned quads and writes them out as binary STL."""

    def __init__(self):
        self._triangles = []

    def add_quad(self, a, b, c, d, normal):
        """Quad a→b→c→d, wound counter-clockwise seen from outside."""
        self._triangles.append((normal, a, b, c))
        self._triangles.append((normal, a, c, d))

    @property
    def triangle_count(self) -> int:
        return len(self._triangles)

    def to_stl_bytes(self, header: str = "Photo Frame 3D") -> bytes:
        buffer = io.BytesIO()
        buffer.write(header.encode("ascii", "replace")[:80].ljust(80, b"\0"))
        buffer.write(struct.pack("<I", len(self._triangles)))

        pack = struct.Struct("<12fH").pack
        for normal, a, b, c in self._triangles:
            buffer.write(pack(*normal, *a, *b, *c, 0))

        return buffer.getvalue()

    def edge_ledger(self) -> Counter:
        """Directed edge counts, used to prove the surface is closed."""
        ledger = Counter()
        for _, a, b, c in self._triangles:
            for start, end in ((a, b), (b, c), (c, a)):
                ledger[(start, end)] += 1
        return ledger


def mesh_is_closed(builder: MeshBuilder) -> bool:
    """True when every directed edge has exactly one opposite twin."""
    ledger = builder.edge_ledger()
    for (start, end), count in ledger.items():
        if count != 1 or ledger.get((end, start), 0) != 1:
            return False
    return True


def build_mesh(heights: np.ndarray, width_mm: float, height_mm: float, levels=None) -> MeshBuilder:
    """
    Build the plate from a height map.

    heights[row][col] is the top of that cell in millimetres. Row 0 is the top
    of the image and is placed at high Y, so the model matches the picture when
    viewed from +Z.

    `levels` is the sorted set of z values a wall may be split at. Every wall is
    subdivided at those heights, which is what keeps the mesh manifold: where
    four cells of different heights meet, the walls around that corner then
    share identical edge segments instead of forming a T-junction.
    """
    rows, cols = heights.shape

    if levels is None:
        levels = sorted({0.0} | {float(value) for value in np.unique(heights)})
    else:
        levels = sorted({0.0} | {float(value) for value in levels})

    def segments(z_low: float, z_high: float):
        """Split [z_low, z_high] at every canonical level in between."""
        inner = [z for z in levels if z_low < z < z_high]
        stops = [z_low, *inner, z_high]
        return list(zip(stops[:-1], stops[1:]))
    dx = width_mm / cols
    dy = height_mm / rows

    builder = MeshBuilder()

    def x_at(col):
        return round(col * dx, 6)

    def y_at(row):
        # Flip so the image's first row ends up at the top of the model.
        return round((rows - row) * dy, 6)

    # --- top surface, one quad per cell ---
    #
    # Deliberately NOT merged into wider strips: a merged quad would leave a
    # T-junction where the neighbouring per-cell walls meet it, which makes the
    # surface non-manifold even though it looks closed. Slicers dislike that.
    for row in range(rows):
        y_top, y_bottom = y_at(row), y_at(row + 1)
        for col in range(cols):
            z = float(heights[row, col])
            x0, x1 = x_at(col), x_at(col + 1)
            builder.add_quad(
                (x0, y_bottom, z), (x1, y_bottom, z), (x1, y_top, z), (x0, y_top, z),
                (0.0, 0.0, 1.0),
            )

    # --- bottom: one quad per cell too, so its edges match the side walls ---
    for row in range(rows):
        y_top, y_bottom = y_at(row), y_at(row + 1)
        for col in range(cols):
            x0, x1 = x_at(col), x_at(col + 1)
            # Reversed winding: this face looks down.
            builder.add_quad(
                (x0, y_bottom, 0.0), (x0, y_top, 0.0), (x1, y_top, 0.0), (x1, y_bottom, 0.0),
                (0.0, 0.0, -1.0),
            )

    # --- walls between columns (planes of constant X) ---
    for row in range(rows):
        y_top, y_bottom = y_at(row), y_at(row + 1)
        for col in range(cols + 1):
            left = float(heights[row, col - 1]) if col > 0 else 0.0
            right = float(heights[row, col]) if col < cols else 0.0
            if left == right:
                continue

            x = x_at(col)
            for z0, z1 in segments(*sorted((left, right))):
                if left > right:
                    # Exposed face looks toward +X.
                    builder.add_quad(
                        (x, y_bottom, z0), (x, y_top, z0), (x, y_top, z1), (x, y_bottom, z1),
                        (1.0, 0.0, 0.0),
                    )
                else:
                    builder.add_quad(
                        (x, y_bottom, z0), (x, y_bottom, z1), (x, y_top, z1), (x, y_top, z0),
                        (-1.0, 0.0, 0.0),
                    )

    # --- walls between rows (planes of constant Y) ---
    for col in range(cols):
        x0, x1 = x_at(col), x_at(col + 1)
        for row in range(rows + 1):
            above = float(heights[row - 1, col]) if row > 0 else 0.0
            below = float(heights[row, col]) if row < rows else 0.0
            if above == below:
                continue

            y = y_at(row)
            for z0, z1 in segments(*sorted((above, below))):
                if above > below:
                    # Row above is taller: its face looks toward -Y (down the image).
                    builder.add_quad(
                        (x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1),
                        (0.0, -1.0, 0.0),
                    )
                else:
                    builder.add_quad(
                        (x0, y, z0), (x0, y, z1), (x1, y, z1), (x1, y, z0),
                        (0.0, 1.0, 0.0),
                    )

    return builder


def order_to_stl(
    image: Image.Image,
    colors,
    layer_heights_mm,
    width_mm: float,
    height_mm: float,
    max_resolution: int = 400,
    header: str = "Photo Frame 3D",
) -> tuple:
    """
    Render an order's layered image into binary STL bytes.

    Returns (stl_bytes, stats) where stats describes the generated model.
    """
    if not colors:
        raise ValueError("پروفایل رنگی این سفارش هیچ رنگی ندارد.")
    if len(layer_heights_mm) != len(colors):
        raise ValueError("تعداد ارتفاع‌ها با تعداد رنگ‌ها یکسان نیست.")
    if width_mm <= 0 or height_mm <= 0:
        raise ValueError("اندازهٔ قاب برای ساخت مدل سه‌بعدی معتبر نیست.")

    indices = layer_index_map(image, colors, max_resolution)
    rows, cols = indices.shape

    if rows * cols > MAX_CELLS:
        raise ValueError("دقت انتخاب‌شده برای مدل سه‌بعدی بیش از حد بالاست.")

    indices, repaired = resolve_saddles(indices)

    lookup = np.array(layer_heights_mm, dtype=np.float64)
    heights = lookup[indices]

    builder = build_mesh(heights, width_mm, height_mm, levels=layer_heights_mm)
    payload = builder.to_stl_bytes(header)

    used = np.bincount(indices.ravel(), minlength=len(colors))
    stats = {
        "grid": (int(cols), int(rows)),
        "repaired_cells": repaired,
        "triangles": builder.triangle_count,
        "bytes": len(payload),
        "width_mm": round(width_mm, 2),
        "height_mm": round(height_mm, 2),
        "max_height_mm": round(float(heights.max()), 2),
        "min_height_mm": round(float(heights.min()), 2),
        "layer_pixel_counts": [int(value) for value in used],
    }
    return payload, stats
