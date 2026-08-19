"""
Safe handling of images the public uploads.

Everything a visitor sends goes through `normalise_upload()` before anything
else looks at it. It exists for three reasons:

1.  **Orientation.** A phone stores a portrait photo as landscape pixels plus
    an EXIF tag saying "rotate me". Ignoring that tag renders the picture
    sideways *and* inverts the aspect ratio, which is what decides the shape of
    the physical frame — so the customer receives a landscape frame for a
    portrait photo.

2.  **Cost.** Processing time grows far faster than pixel count. A 12 MP phone
    photo can occupy a worker for minutes, and the workers are shared. Since
    posterising to a handful of flat colours destroys fine detail anyway,
    working above a couple of megapixels buys nothing visible.

3.  **Safety.** An image file's size on disk says nothing about how much memory
    it needs once decoded. A few hundred kilobytes of PNG can expand to
    gigapixels, so dimensions are checked from the header *before* any pixels
    are decoded.
"""

import io

from django.conf import settings
from PIL import Image, ImageOps

# Refuse outright above this. Well beyond any real camera, and low enough that
# a decompression bomb cannot exhaust memory.
MAX_UPLOAD_PIXELS = getattr(settings, "MAX_UPLOAD_PIXELS", 40_000_000)

# Work at or below this. Posterisation flattens detail into a few colours, so
# extra resolution costs processing time and returns nothing the eye can see.
WORKING_PIXELS = getattr(settings, "WORKING_PIXELS", 2_000_000)

# Pillow's own guard. Left slightly above ours so our clearer error comes first.
Image.MAX_IMAGE_PIXELS = MAX_UPLOAD_PIXELS * 2


class UploadRejected(Exception):
    """Carries a message meant for the visitor, in Persian."""


def _fa(number) -> str:
    return str(number).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def inspect(image_bytes: bytes) -> tuple:
    """
    (width, height) straight from the header, without decoding the image.

    Raises UploadRejected for anything that is not a readable image or is
    larger than we are willing to decode.
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as probe:
            # size comes from the header alone. Checking it here, before
            # verify() touches any pixel data, is what keeps a decompression
            # bomb from being decoded at all — and lets us explain why.
            width, height = probe.size
            _check_dimensions(width, height)
            probe.verify()
    except UploadRejected:
        raise
    except Image.DecompressionBombError:
        # Pillow's own guard fires inside open(), before we get to read .size.
        raise UploadRejected(
            "ابعاد این تصویر بیش از حد بزرگ است و پردازش نمی‌شود."
        )
    except Exception:
        raise UploadRejected("فایل انتخاب‌شده یک تصویر معتبر نیست.")

    return width, height


def _check_dimensions(width: int, height: int) -> None:
    if width < 8 or height < 8:
        raise UploadRejected("این تصویر بیش از حد کوچک است.")

    if width * height > MAX_UPLOAD_PIXELS:
        megapixels = MAX_UPLOAD_PIXELS // 1_000_000
        raise UploadRejected(
            f"ابعاد این تصویر بیش از حد بزرگ است ({_fa(width)}×{_fa(height)} پیکسل). "
            f"حداکثر {_fa(megapixels)} مگاپیکسل پذیرفته می‌شود."
        )


def normalise_upload(image_bytes: bytes, *, lossless: bool = True) -> tuple:
    """
    Turn a raw upload into the copy the rest of the app works from.

    Applies the EXIF rotation, drops the now-meaningless metadata, converts to
    RGB and scales down to `WORKING_PIXELS` if needed. Returns
    (png_bytes, info) where info records what happened, for logging and tests.

    `lossless` is always honoured for ready-made images: re-encoding those with
    JPEG would add exactly the compression noise their colour check is built to
    detect.
    """
    original_width, original_height = inspect(image_bytes)

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            # Must happen before anything measures the image: this is what
            # turns a phone's landscape pixels back into a portrait photo.
            image = ImageOps.exif_transpose(image)
            if image.mode != "RGB":
                image = image.convert("RGB")

            rotated = image.size != (original_width, original_height)

            scale = 1.0
            pixels = image.width * image.height
            if pixels > WORKING_PIXELS:
                scale = (WORKING_PIXELS / pixels) ** 0.5
                image = image.resize(
                    (max(8, round(image.width * scale)), max(8, round(image.height * scale))),
                    Image.LANCZOS,
                )

            out = io.BytesIO()
            image.save(out, format="PNG" if lossless else "JPEG", quality=95)
            payload = out.getvalue()
            final_size = image.size
    except UploadRejected:
        raise
    except Image.DecompressionBombError:
        raise UploadRejected("این تصویر بیش از حد بزرگ است.")
    except Exception as exc:
        raise UploadRejected(f"خواندن این تصویر ممکن نبود: {exc}")

    return payload, {
        "original_size": (original_width, original_height),
        "final_size": final_size,
        "rotated_by_exif": rotated,
        "downscaled": scale < 1.0,
        "bytes_in": len(image_bytes),
        "bytes_out": len(payload),
    }
