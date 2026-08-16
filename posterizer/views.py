import base64
import io
import json
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from PIL import Image

from accounts.views import anonymous_payload, user_payload
from main import DEFAULT_CONFIG, process_image_bytes

from .jalali import format_cm, format_toman, to_persian_digits
from .models import ColorProfile, Order, SiteSettings

UPLOAD_DIR = settings.BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_IMAGE_BYTES = settings.MAX_IMAGE_BYTES

# main.py needs cv2.ximgproc for superpixels, which the standard OpenCV wheels
# do not ship. Detect it once so the UI can disable the option honestly.
try:  # pragma: no cover - depends on the installed OpenCV build
    import cv2

    SUPERPIXELS_AVAILABLE = hasattr(cv2, "ximgproc")
except Exception:  # pragma: no cover
    SUPERPIXELS_AVAILABLE = False


# ---------------------------------------------------------------- config ----

def parse_config(form, profile: ColorProfile) -> dict:
    """
    Build the processing config from the submitted form.

    The layer count is no longer chosen by the visitor: it comes from the
    colour profile they picked.
    """

    def get_int(key, default):
        return int(form.get(key, default))

    def get_float(key, default):
        return float(form.get(key, default))

    def get_bool(key, default):
        val = form.get(key)
        if val is None:
            return default
        return val.lower() in ("true", "1", "on", "yes")

    use_superpixels = get_bool("use_superpixels", DEFAULT_CONFIG["use_superpixels"])

    return {
        "num_levels": max(2, profile.num_layers),
        "preprocess_method": form.get("preprocess_method", DEFAULT_CONFIG["preprocess_method"]),
        "gaussian_kernel_size": get_int("gaussian_kernel_size", DEFAULT_CONFIG["gaussian_kernel_size"]),
        "median_kernel_size": get_int("median_kernel_size", DEFAULT_CONFIG["median_kernel_size"]),
        "bilateral_d": get_int("bilateral_d", DEFAULT_CONFIG["bilateral_d"]),
        "bilateral_sigma_color": get_float("bilateral_sigma_color", DEFAULT_CONFIG["bilateral_sigma_color"]),
        "bilateral_sigma_space": get_float("bilateral_sigma_space", DEFAULT_CONFIG["bilateral_sigma_space"]),
        "postprocess_method": form.get("postprocess_method", DEFAULT_CONFIG["postprocess_method"]),
        "morph_kernel_size": get_int("morph_kernel_size", DEFAULT_CONFIG["morph_kernel_size"]),
        "min_region_size": get_int("min_region_size", DEFAULT_CONFIG["min_region_size"]),
        "preserve_edges": get_bool("preserve_edges", DEFAULT_CONFIG["preserve_edges"]),
        "use_superpixels": use_superpixels and SUPERPIXELS_AVAILABLE,
        "superpixel_region_size": get_int("superpixel_region_size", DEFAULT_CONFIG["superpixel_region_size"]),
        "majority_window_size": get_int("majority_window_size", DEFAULT_CONFIG["majority_window_size"]),
    }


def active_profiles():
    return ColorProfile.objects.filter(is_active=True).prefetch_related("layers")


def resolve_profile(form) -> ColorProfile | None:
    """The profile the visitor selected; falls back to the first active one."""
    raw = form.get("profile_id")
    profiles = active_profiles()

    if raw:
        try:
            return profiles.get(pk=int(raw))
        except (ColorProfile.DoesNotExist, ValueError, TypeError):
            return None
    return profiles.first()


# ----------------------------------------------------------- image files ----

def store_original(session_id: str, image_bytes: bytes) -> None:
    (UPLOAD_DIR / f"{session_id}.bin").write_bytes(image_bytes)


def load_original(session_id: str) -> bytes | None:
    path = UPLOAD_DIR / f"{session_id}.bin"
    if not path.exists():
        return None
    return path.read_bytes()


def store_result(session_id: str, image_bytes: bytes) -> None:
    (UPLOAD_DIR / f"{session_id}.result.png").write_bytes(image_bytes)


def load_result(session_id: str) -> bytes | None:
    path = UPLOAD_DIR / f"{session_id}.result.png"
    if not path.exists():
        return None
    return path.read_bytes()


def to_png_bytes(image_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def bytes_to_display_data_url(image_bytes: bytes) -> str:
    encoded = base64.b64encode(to_png_bytes(image_bytes)).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _config_fingerprint(config: dict, profile_id) -> str:
    return json.dumps({"config": config, "profile": profile_id}, sort_keys=True, default=str)


# ---------------------------------------------------------------- sizing ----

def image_dimensions(image_bytes: bytes) -> tuple:
    """(width_px, height_px) read from the header, without decoding pixels."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        return img.size


def sizing_payload(image_bytes: bytes | None = None) -> dict:
    """Frame limits and pricing, narrowed to this image's aspect ratio."""
    site = SiteSettings.load()

    if image_bytes is None:
        return site.as_dict()

    width_px, height_px = image_dimensions(image_bytes)
    ratio = width_px / height_px
    data = site.as_dict(ratio=ratio)
    data.update({
        "image_width_px": width_px,
        "image_height_px": height_px,
        "ratio": ratio,
    })

    if data["fits"]:
        # Start somewhere sensible inside the allowed band.
        low = Decimal(str(data["effective_min_width_cm"]))
        high = Decimal(str(data["effective_max_width_cm"]))
        preferred = Decimal("30")
        default_width = min(max(preferred, low), high)
        default_height = site.height_for_width(default_width, ratio)
        data["default_width_cm"] = float(default_width)
        data["default_height_cm"] = float(default_height)
        data["default_cost"] = site.estimate_cost(default_width, default_height)

    return data


def resolve_frame_size(form, image_bytes: bytes):
    """
    Validate the requested frame size.

    The height is always recomputed from the width and the photo's aspect
    ratio, so a tampered client cannot order a stretched frame.
    Returns (site, width, height, cost) or raises ValueError with a Persian message.
    """
    site = SiteSettings.load()
    width_px, height_px = image_dimensions(image_bytes)
    ratio = Decimal(str(width_px)) / Decimal(str(height_px))

    low, high = site.width_bounds_for_ratio(ratio)
    if low > high:
        raise ValueError(
            "با محدودیت‌های فعلی اندازهٔ قاب، هیچ اندازه‌ای برای نسبت این تصویر ممکن نیست. "
            "لطفاً تصویر دیگری انتخاب کنید یا با پشتیبانی تماس بگیرید."
        )

    raw = form.get("width_cm")
    if raw in (None, ""):
        raise ValueError("لطفاً اندازهٔ قاب را انتخاب کنید.")

    try:
        width = Decimal(str(to_ascii_number(raw)))
    except (InvalidOperation, ValueError):
        raise ValueError("اندازهٔ وارد شده معتبر نیست.")

    if width < low or width > high:
        raise ValueError(
            f"عرض قاب باید بین {format_cm(low)} تا {format_cm(high)} سانتی‌متر باشد."
        )

    height = site.height_for_width(width, ratio)
    if height < site.min_height_cm or height > site.max_height_cm:
        raise ValueError(
            f"ارتفاع متناظر ({format_cm(height)} سانتی‌متر) خارج از محدودهٔ مجاز است."
        )

    return site, width, height, site.estimate_cost(width, height)


def to_ascii_number(value: str) -> str:
    """Accept Persian/Arabic numerals in numeric form fields."""
    table = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫", "01234567890123456789.")
    return str(value).translate(table).strip()


# ----------------------------------------------------------------- pages ----

@ensure_csrf_cookie
@require_GET
def index(request):
    """The studio page. Deliberately open to anonymous visitors."""
    profiles = list(active_profiles())

    context = {
        "default_config": DEFAULT_CONFIG,
        "profiles": profiles,
        "profiles_json": [profile.as_dict() for profile in profiles],
        "sizing": sizing_payload(),
        "superpixels_available": SUPERPIXELS_AVAILABLE,
        "max_unreviewed": Order.MAX_UNREVIEWED,
        "open_login": request.GET.get("login") == "1",
        "account": user_payload(request.user)
        if request.user.is_authenticated
        else anonymous_payload(),
    }
    return render(request, "index.html", context)


@login_required
@require_GET
def my_orders(request):
    orders = (
        Order.objects.filter(user=request.user).select_related("profile").order_by("-created_at")
    )
    return render(
        request,
        "orders.html",
        {
            "orders": orders,
            "unreviewed_count": Order.objects.unreviewed_count(request.user),
            "max_unreviewed": Order.MAX_UNREVIEWED,
            "account": user_payload(request.user),
        },
    )


@login_required
@require_GET
def order_image(request, pk: int, kind: str):
    """
    Stream an order's image.

    Order images are private, so they are never served straight off disk:
    only the owner and admins may fetch one.
    """
    if kind not in ("result", "original"):
        raise Http404

    order = get_object_or_404(Order, pk=pk)
    if order.user_id != request.user.id and not request.user.is_staff:
        raise Http404

    field = order.result_image if kind == "result" else order.original_image
    if not field:
        raise Http404

    return FileResponse(field.open("rb"), content_type="image/png")


# ------------------------------------------------------------------ APIs ----

@require_GET
def get_config(request):
    return JsonResponse({
        "defaults": DEFAULT_CONFIG,
        "profiles": [profile.as_dict() for profile in active_profiles()],
        "sizing": sizing_payload(),
        "superpixels_available": SUPERPIXELS_AVAILABLE,
    })


@require_POST
def process(request):
    try:
        profile = resolve_profile(request.POST)
        if profile is None:
            return JsonResponse(
                {"error": "پروفایل رنگی انتخاب‌شده معتبر نیست. لطفاً یکی از پروفایل‌ها را انتخاب کنید."},
                status=400,
            )

        config = parse_config(request.POST, profile)
        file = request.FILES.get("image")
        session_id = request.session.get("image_id")

        if file and file.name:
            image_bytes = file.read()
            if len(image_bytes) > MAX_IMAGE_BYTES:
                return JsonResponse(
                    {"error": "حجم تصویر بیش از حد مجاز است (حداکثر ۲۰ مگابایت)."}, status=400
                )

            try:
                Image.open(io.BytesIO(image_bytes)).verify()
            except Exception:
                return JsonResponse({"error": "فایل انتخاب‌شده یک تصویر معتبر نیست."}, status=400)

            session_id = uuid.uuid4().hex
            request.session["image_id"] = session_id
            store_original(session_id, image_bytes)
        elif session_id:
            image_bytes = load_original(session_id)
            if image_bytes is None:
                return JsonResponse(
                    {"error": "تصویری یافت نشد. لطفاً ابتدا یک تصویر بارگذاری کنید."}, status=400
                )
        else:
            return JsonResponse({"error": "هیچ تصویری بارگذاری نشده است."}, status=400)

        colors = profile.color_list()
        result_bytes = process_image_bytes(image_bytes, colors=colors, **config)

        # Keep the exact render around so submitting an order does not have to
        # redo the work (and cannot drift from what the user just saw).
        store_result(session_id, result_bytes)
        request.session["last_render"] = _config_fingerprint(config, profile.id)

        return JsonResponse({
            "result_url": bytes_to_display_data_url(result_bytes),
            "original_url": bytes_to_display_data_url(image_bytes),
            "config": config,
            "profile": profile.as_dict(),
            "sizing": sizing_payload(image_bytes),
            "session_id": session_id,
        })
    except RuntimeError as exc:
        if "ximgproc" in str(exc):
            return JsonResponse(
                {"error": "قابلیت سوپرپیکسل روی این سرور در دسترس نیست."}, status=400
            )
        return JsonResponse({"error": f"پردازش تصویر ناموفق بود: {exc}"}, status=500)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"error": f"پردازش تصویر ناموفق بود: {exc}"}, status=500)


@require_POST
def order_create(request):
    """Submit the freshly built image as an order for admin review."""
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "ok": False,
                "auth_required": True,
                "error": "برای ثبت سفارش ابتدا وارد حساب کاربری خود شوید.",
            },
            status=401,
        )

    profile = resolve_profile(request.POST)
    if profile is None:
        return JsonResponse(
            {"ok": False, "error": "پروفایل رنگی انتخاب‌شده معتبر نیست."}, status=400
        )

    session_id = request.session.get("image_id")
    original_bytes = load_original(session_id) if session_id else None
    if original_bytes is None:
        return JsonResponse(
            {"ok": False, "error": "تصویری برای ثبت سفارش یافت نشد. ابتدا یک تصویر بسازید."},
            status=400,
        )

    config = parse_config(request.POST, profile)
    note = (request.POST.get("note") or "").strip()[:2000]

    # The frame size is re-validated and the height re-derived from the photo's
    # own aspect ratio, so the price cannot be gamed from the browser.
    try:
        site, width_cm, height_cm, estimated_cost = resolve_frame_size(
            request.POST, original_bytes
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    try:
        with transaction.atomic():
            # Re-check inside the transaction so two quick clicks cannot slip
            # past the three-order limit.
            unreviewed = Order.objects.filter(user=request.user).unreviewed().count()
            if unreviewed >= Order.MAX_UNREVIEWED:
                return JsonResponse(
                    {
                        "ok": False,
                        "limit_reached": True,
                        "error": (
                            f"شما {to_persian_digits(Order.MAX_UNREVIEWED)} سفارش بررسی‌نشده دارید. "
                            "تا بررسی آن‌ها امکان ثبت سفارش جدید وجود ندارد."
                        ),
                    },
                    status=400,
                )

            # Reuse the render the visitor is looking at; only redo the work if
            # the settings changed since the last preview.
            result_bytes = None
            if request.session.get("last_render") == _config_fingerprint(config, profile.id):
                result_bytes = load_result(session_id)
            if result_bytes is None:
                result_bytes = process_image_bytes(
                    original_bytes, colors=profile.color_list(), **config
                )

            order = Order(
                user=request.user,
                profile=profile,
                profile_name=profile.name,
                num_layers=profile.num_layers,
                colors=profile.color_list(),
                config=config,
                note=note,
                status=Order.STATUS_PENDING,
                width_cm=width_cm,
                height_cm=height_cm,
                area_cm2=width_cm * height_cm,
                price_per_cm2=site.price_per_cm2,
                estimated_cost=estimated_cost,
            )
            order.result_image.save(f"{uuid.uuid4().hex}.png", ContentFile(result_bytes), save=False)
            order.original_image.save(
                f"{uuid.uuid4().hex}.png", ContentFile(to_png_bytes(original_bytes)), save=False
            )
            order.save()
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"ثبت سفارش ناموفق بود: {exc}"}, status=500)

    return JsonResponse({
        "ok": True,
        "message": "سفارش شما با موفقیت ثبت شد و در انتظار بررسی است.",
        "order": {
            "id": order.pk,
            "status": order.status,
            "status_label": order.get_status_display(),
            "profile": order.profile_name,
            "num_layers": order.num_layers,
            "size": order.size_label,
            "estimated_cost": order.estimated_cost,
            "estimated_cost_label": format_toman(order.estimated_cost),
        },
        "user": user_payload(request.user),
    })
