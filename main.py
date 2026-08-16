#!/usr/bin/env python3
"""
grayscale_posterize.py

Convert an input image into a stylized grayscale posterized image with a fixed
number of grayscale levels and optional noise/fragment cleanup.

Dependencies:
    pip install opencv-python numpy pillow scikit-image scipy

Example:
    python grayscale_posterize.py input.jpg output.png --num-levels 4 \
        --preprocess bilateral \
        --bilateral-d 7 \
        --bilateral-sigma-color 40 \
        --bilateral-sigma-space 40 \
        --postprocess connected_components \
        --min-region-size 100
"""

import argparse
import os
import cv2
import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import measure


# -----------------------------
# Utility helpers
# -----------------------------

def ensure_odd(value: int) -> int:
    """Ensure kernel size is odd and at least 1."""
    value = max(1, int(value))
    if value % 2 == 0:
        value += 1
    return value


def load_image_grayscale(path: str) -> np.ndarray:
    """
    Load image and convert to grayscale uint8 array.
    Uses Pillow for robust reading, returns ndarray shape (H, W).
    """
    img = Image.open(path).convert("L")
    return np.array(img, dtype=np.uint8)


def save_image(path: str, image: np.ndarray) -> None:
    """Save uint8 grayscale image."""
    Image.fromarray(image.astype(np.uint8), mode="L").save(path)


def get_evenly_spaced_levels(num_levels: int) -> np.ndarray:
    """
    Return exactly num_levels grayscale tones evenly spaced from 0 to 255.
    Example:
        2 -> [0, 255]
        3 -> [0, 127, 255]
        5 -> [0, 64, 128, 191, 255]
    """
    if num_levels < 2:
        raise ValueError("num_levels must be >= 2")
    return np.round(np.linspace(0, 255, num_levels)).astype(np.uint8)


# -----------------------------
# Layer colouring
# -----------------------------

def hex_to_rgb(value: str) -> tuple:
    """Convert '#rrggbb' (or 'rrggbb') into an (r, g, b) tuple."""
    value = str(value).strip().lstrip("#")
    if len(value) == 3:  # allow the shorthand '#abc'
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"Invalid hex colour: {value}")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def build_level_lut(num_levels: int, colors) -> np.ndarray:
    """
    Build a 256x3 lookup table mapping every grey value to a layer colour.

    Entry i holds the colour of whichever quantization level is nearest to i,
    so the table stays correct even if a stray value survives post-processing.
    """
    levels = get_evenly_spaced_levels(num_levels).astype(np.int16)
    rgb = [hex_to_rgb(color) for color in colors]

    if len(rgb) != num_levels:
        raise ValueError(
            f"Expected {num_levels} colours for {num_levels} levels, got {len(rgb)}"
        )

    lut = np.zeros((256, 3), dtype=np.uint8)
    for value in range(256):
        nearest = int(np.argmin(np.abs(levels - value)))
        lut[value] = rgb[nearest]
    return lut


def apply_level_colors(quantized: np.ndarray, num_levels: int, colors) -> np.ndarray:
    """Map a quantized grayscale image onto per-layer colours -> RGB array."""
    lut = build_level_lut(num_levels, colors)
    return lut[quantized]


# -----------------------------
# Preprocessing methods
# -----------------------------

def preprocess_image(
    gray: np.ndarray,
    method: str = "none",
    gaussian_kernel_size: int = 5,
    median_kernel_size: int = 5,
    bilateral_d: int = 7,
    bilateral_sigma_color: float = 40,
    bilateral_sigma_space: float = 40
) -> np.ndarray:
    """
    Apply optional pre-smoothing before quantization.
    """
    method = method.lower()

    if method == "none":
        return gray.copy()

    if method == "gaussian":
        k = ensure_odd(gaussian_kernel_size)
        return cv2.GaussianBlur(gray, (k, k), 0)

    if method == "median":
        k = ensure_odd(median_kernel_size)
        return cv2.medianBlur(gray, k)

    if method == "bilateral":
        # Bilateral is edge-preserving and often best for stylized posterization
        return cv2.bilateralFilter(
            gray,
            d=int(bilateral_d),
            sigmaColor=float(bilateral_sigma_color),
            sigmaSpace=float(bilateral_sigma_space)
        )

    raise ValueError(f"Unknown preprocess method: {method}")


# -----------------------------
# Quantization
# -----------------------------

def quantize_to_levels(gray: np.ndarray, num_levels: int) -> np.ndarray:
    """
    Quantize grayscale values to nearest tone among evenly spaced levels.
    """
    levels = get_evenly_spaced_levels(num_levels).astype(np.int16)
    gray16 = gray.astype(np.int16)

    # Compute nearest level for each pixel
    # shape: (H, W, num_levels)
    diffs = np.abs(gray16[..., None] - levels[None, None, :])
    nearest_idx = np.argmin(diffs, axis=2)
    quantized = levels[nearest_idx].astype(np.uint8)
    return quantized


# -----------------------------
# Postprocessing methods
# -----------------------------

def postprocess_median(image: np.ndarray, kernel_size: int = 3) -> np.ndarray:
    """Median filter after quantization to suppress isolated pixels."""
    k = ensure_odd(kernel_size)
    return cv2.medianBlur(image, k)


def postprocess_morphology(image: np.ndarray, kernel_size: int = 3) -> np.ndarray:
    """
    Apply morphology separately to each grayscale class.
    This helps remove small holes/fragments while preserving discrete levels.
    """
    k = ensure_odd(kernel_size)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))

    levels = np.unique(image)
    result = image.copy()

    # Work class-by-class to avoid introducing unintended grayscale values
    for level in levels:
        mask = (image == level).astype(np.uint8) * 255

        # Opening removes tiny bright specks in the class mask
        opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        # Closing fills small holes inside class regions
        closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)

        # Update regions where this class is strong after cleanup
        result[closed > 127] = level

    # Re-quantize to ensure only original class values remain
    result = snap_to_existing_levels(result, levels)
    return result


def snap_to_existing_levels(image: np.ndarray, levels: np.ndarray) -> np.ndarray:
    """
    Snap arbitrary grayscale image to nearest available levels.
    Useful after operations that may slightly alter values.
    """
    levels = np.array(levels, dtype=np.int16)
    img16 = image.astype(np.int16)
    diffs = np.abs(img16[..., None] - levels[None, None, :])
    idx = np.argmin(diffs, axis=2)
    return levels[idx].astype(np.uint8)


def majority_filter(image: np.ndarray, window_size: int = 3) -> np.ndarray:
    """
    Mode/majority filter over local neighborhoods.
    Replaces each pixel with the most common value in its neighborhood.
    Very effective for removing small isolated label noise after quantization.
    """
    window_size = ensure_odd(window_size)
    pad = window_size // 2
    padded = np.pad(image, pad, mode='edge')
    result = np.zeros_like(image)

    # Since the number of grayscale levels is small, mode filtering is manageable
    for y in range(image.shape[0]):
        for x in range(image.shape[1]):
            patch = padded[y:y + window_size, x:x + window_size]
            values, counts = np.unique(patch, return_counts=True)
            result[y, x] = values[np.argmax(counts)]

    return result


def merge_small_connected_components(
    image: np.ndarray,
    min_region_size: int = 50
) -> np.ndarray:
    """
    Detect small connected regions of each grayscale level and merge them into
    neighboring larger regions based on surrounding pixel tones.

    Strategy:
    - For each level separately:
        - Find connected components
        - If a component is smaller than min_region_size:
            - Look at 1-pixel dilated border around the component
            - Assign component to the most common neighboring grayscale level
    """
    result = image.copy()
    levels = np.unique(image)

    changed = True
    iteration = 0
    max_iterations = 5  # avoid endless loops

    while changed and iteration < max_iterations:
        changed = False
        iteration += 1

        for level in levels:
            mask = (result == level).astype(np.uint8)

            labeled = measure.label(mask, connectivity=2)
            props = measure.regionprops(labeled)

            for region in props:
                if region.area >= min_region_size:
                    continue

                coords = region.coords
                region_mask = np.zeros_like(mask, dtype=np.uint8)
                region_mask[coords[:, 0], coords[:, 1]] = 1

                # Dilate region to get border neighborhood
                kernel = np.ones((3, 3), np.uint8)
                dilated = cv2.dilate(region_mask, kernel, iterations=1)
                border = (dilated == 1) & (region_mask == 0)

                neighbor_values = result[border]
                if neighbor_values.size == 0:
                    continue

                # Exclude same level if possible, to encourage merging outward
                neighbor_values_filtered = neighbor_values[neighbor_values != level]
                if neighbor_values_filtered.size > 0:
                    neighbor_values = neighbor_values_filtered

                vals, counts = np.unique(neighbor_values, return_counts=True)
                new_level = vals[np.argmax(counts)]

                result[coords[:, 0], coords[:, 1]] = new_level
                changed = True

    return result


# -----------------------------
# Optional advanced method
# -----------------------------

def superpixel_simplification(gray: np.ndarray, num_levels: int, region_size: int = 25) -> np.ndarray:
    """
    Optional advanced simplification using OpenCV SLIC superpixels if available.
    Each superpixel gets a single quantized grayscale level based on mean intensity.

    Note:
    - Requires cv2.ximgproc.createSuperpixelSLIC
    - If unavailable, caller should skip this method
    """
    if not hasattr(cv2, "ximgproc"):
        raise RuntimeError("OpenCV ximgproc module not available for superpixels.")

    # SLIC expects 3-channel image
    color = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    slic = cv2.ximgproc.createSuperpixelSLIC(
        color,
        algorithm=cv2.ximgproc.SLIC,
        region_size=region_size,
        ruler=10.0
    )
    slic.iterate(10)
    labels = slic.getLabels()
    num_superpixels = slic.getNumberOfSuperpixels()

    levels = get_evenly_spaced_levels(num_levels)
    output = np.zeros_like(gray, dtype=np.uint8)

    for label_id in range(num_superpixels):
        mask = (labels == label_id)
        if not np.any(mask):
            continue

        mean_val = int(np.mean(gray[mask]))
        nearest_level = levels[np.argmin(np.abs(levels.astype(np.int16) - mean_val))]
        output[mask] = nearest_level

    return output


# -----------------------------
# Main pipeline
# -----------------------------

def process_grayscale_array(
    gray: np.ndarray,
    num_levels: int,
    preprocess_method: str = "bilateral",
    gaussian_kernel_size: int = 5,
    median_kernel_size: int = 5,
    bilateral_d: int = 7,
    bilateral_sigma_color: float = 40,
    bilateral_sigma_space: float = 40,
    postprocess_method: str = "connected_components",
    morph_kernel_size: int = 3,
    min_region_size: int = 50,
    preserve_edges: bool = True,
    use_superpixels: bool = False,
    superpixel_region_size: int = 25,
    majority_window_size: int = 3,
) -> np.ndarray:
    """
    Full grayscale posterization pipeline on an in-memory grayscale array.
    """
    if preserve_edges and preprocess_method == "gaussian":
        pass

    if use_superpixels:
        poster = superpixel_simplification(gray, num_levels, region_size=superpixel_region_size)
    else:
        smoothed = preprocess_image(
            gray,
            method=preprocess_method,
            gaussian_kernel_size=gaussian_kernel_size,
            median_kernel_size=median_kernel_size,
            bilateral_d=bilateral_d,
            bilateral_sigma_color=bilateral_sigma_color,
            bilateral_sigma_space=bilateral_sigma_space,
        )
        poster = quantize_to_levels(smoothed, num_levels)

    ppm = postprocess_method.lower()

    if ppm == "none":
        final = poster
    elif ppm == "median":
        final = postprocess_median(poster, kernel_size=median_kernel_size)
        final = quantize_to_levels(final, num_levels)
    elif ppm == "morphology":
        final = postprocess_morphology(poster, kernel_size=morph_kernel_size)
        final = quantize_to_levels(final, num_levels)
    elif ppm == "connected_components":
        final = merge_small_connected_components(poster, min_region_size=min_region_size)
        final = quantize_to_levels(final, num_levels)
    elif ppm == "majority_filter":
        final = majority_filter(poster, window_size=majority_window_size)
        final = quantize_to_levels(final, num_levels)
    else:
        raise ValueError(f"Unknown postprocess method: {postprocess_method}")

    return final


def process_image_bytes(image_bytes: bytes, colors=None, **kwargs) -> bytes:
    """
    Load image bytes, process, and return PNG bytes.

    When `colors` is given it must hold one hex colour per grayscale level; the
    result is then an RGB image using those colours instead of grey tones.
    """
    import io

    img = Image.open(io.BytesIO(image_bytes)).convert("L")
    gray = np.array(img, dtype=np.uint8)
    result = process_grayscale_array(gray, **kwargs)

    out = io.BytesIO()
    if colors:
        colored = apply_level_colors(result, kwargs["num_levels"], colors)
        Image.fromarray(colored, mode="RGB").save(out, format="PNG")
    else:
        Image.fromarray(result.astype(np.uint8), mode="L").save(out, format="PNG")
    return out.getvalue()


def process_image(
    input_path: str,
    output_path: str,
    num_levels: int,
    preprocess_method: str = "bilateral",
    gaussian_kernel_size: int = 5,
    median_kernel_size: int = 5,
    bilateral_d: int = 7,
    bilateral_sigma_color: float = 40,
    bilateral_sigma_space: float = 40,
    postprocess_method: str = "connected_components",
    morph_kernel_size: int = 3,
    min_region_size: int = 50,
    preserve_edges: bool = True,
    use_superpixels: bool = False,
    superpixel_region_size: int = 25,
    majority_window_size: int = 3
) -> np.ndarray:
    """
    Full grayscale posterization pipeline.
    """
    gray = load_image_grayscale(input_path)
    final = process_grayscale_array(
        gray,
        num_levels=num_levels,
        preprocess_method=preprocess_method,
        gaussian_kernel_size=gaussian_kernel_size,
        median_kernel_size=median_kernel_size,
        bilateral_d=bilateral_d,
        bilateral_sigma_color=bilateral_sigma_color,
        bilateral_sigma_space=bilateral_sigma_space,
        postprocess_method=postprocess_method,
        morph_kernel_size=morph_kernel_size,
        min_region_size=min_region_size,
        preserve_edges=preserve_edges,
        use_superpixels=use_superpixels,
        superpixel_region_size=superpixel_region_size,
        majority_window_size=majority_window_size,
    )

    save_image(output_path, final)
    return final


# -----------------------------
# CLI
# -----------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="Convert an image into a stylized grayscale posterized image with cleanup."
    )

    parser.add_argument("input_path", help="Path to input image")
    parser.add_argument("output_path", help="Path to output image")
    parser.add_argument("--num-levels", type=int, required=True, help="Number of grayscale levels (>=2)")

    parser.add_argument(
        "--preprocess",
        type=str,
        default="bilateral",
        choices=["none", "gaussian", "median", "bilateral"],
        help="Pre-smoothing method"
    )
    parser.add_argument("--gaussian-kernel-size", type=int, default=5)
    parser.add_argument("--median-kernel-size", type=int, default=5)
    parser.add_argument("--bilateral-d", type=int, default=7)
    parser.add_argument("--bilateral-sigma-color", type=float, default=40)
    parser.add_argument("--bilateral-sigma-space", type=float, default=40)

    parser.add_argument(
        "--postprocess",
        type=str,
        default="connected_components",
        choices=["none", "median", "morphology", "connected_components", "majority_filter"],
        help="Post-processing cleanup method"
    )
    parser.add_argument("--morph-kernel-size", type=int, default=3)
    parser.add_argument("--min-region-size", type=int, default=50)
    parser.add_argument("--majority-window-size", type=int, default=3)

    parser.add_argument(
        "--preserve-edges",
        action="store_true",
        help="Prefer edge-preserving settings; mainly useful conceptually with bilateral filtering"
    )

    parser.add_argument(
        "--use-superpixels",
        action="store_true",
        help="Optional advanced simplification using superpixels"
    )
    parser.add_argument("--superpixel-region-size", type=int, default=25)

    return parser



NUM_LEVELS = 4

PREPROCESS_METHOD = "bilateral"
GAUSSIAN_KERNEL_SIZE = 5
MEDIAN_KERNEL_SIZE = 5

BILATERAL_D = 7
BILATERAL_SIGMA_COLOR = 45
BILATERAL_SIGMA_SPACE = 45

POSTPROCESS_METHOD = "connected_components"
MORPH_KERNEL_SIZE = 3
MIN_REGION_SIZE = 60

PRESERVE_EDGES = True

# Optional superpixel processing
USE_SUPERPIXELS = False
SUPERPIXEL_REGION_SIZE = 25

# Used by the majority_filter method
MAJORITY_WINDOW_SIZE = 3


DEFAULT_CONFIG = {
    "num_levels": NUM_LEVELS,
    "preprocess_method": PREPROCESS_METHOD,
    "gaussian_kernel_size": GAUSSIAN_KERNEL_SIZE,
    "median_kernel_size": MEDIAN_KERNEL_SIZE,
    "bilateral_d": BILATERAL_D,
    "bilateral_sigma_color": BILATERAL_SIGMA_COLOR,
    "bilateral_sigma_space": BILATERAL_SIGMA_SPACE,
    "postprocess_method": POSTPROCESS_METHOD,
    "morph_kernel_size": MORPH_KERNEL_SIZE,
    "min_region_size": MIN_REGION_SIZE,
    "preserve_edges": PRESERVE_EDGES,
    "use_superpixels": USE_SUPERPIXELS,
    "superpixel_region_size": SUPERPIXEL_REGION_SIZE,
    "majority_window_size": MAJORITY_WINDOW_SIZE,
}


def main():
    """Standalone CLI. The web app imports this module instead."""
    args = build_parser().parse_args()

    if not os.path.exists(args.input_path):
        raise FileNotFoundError(f"Input file does not exist: {args.input_path}")

    process_image(
        input_path=args.input_path,
        output_path=args.output_path,
        num_levels=args.num_levels,
        preprocess_method=args.preprocess,
        gaussian_kernel_size=args.gaussian_kernel_size,
        median_kernel_size=args.median_kernel_size,
        bilateral_d=args.bilateral_d,
        bilateral_sigma_color=args.bilateral_sigma_color,
        bilateral_sigma_space=args.bilateral_sigma_space,
        postprocess_method=args.postprocess,
        morph_kernel_size=args.morph_kernel_size,
        min_region_size=args.min_region_size,
        preserve_edges=args.preserve_edges,
        use_superpixels=args.use_superpixels,
        superpixel_region_size=args.superpixel_region_size,
        majority_window_size=args.majority_window_size,
    )

    print(f"Saved processed image to: {args.output_path}")


if __name__ == "__main__":
    main()
