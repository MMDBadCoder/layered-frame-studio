import base64
import io
import json
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from PIL import Image

from accounts.views import anonymous_payload, user_payload
from main import DEFAULT_CONFIG, process_image_bytes

from .jalali import format_cm, format_toman, to_persian_digits
from .models import ColorProfile, Order, SiteSettings
from .ready import prepare_ready_image, verify_ready_image
from .stl import order_to_stl

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

def parse_config(form, profile: ColorProfile, defaults: dict | None = None) -> dict:
    """
    Build the processing config from the submitted form.

    Anything the visitor did not send falls back to the admin-configured
    studio defaults. The layer count is never taken from the form: it comes
    from the colour profile they picked.
    """
    defaults = defaults or SiteSettings.load().render_defaults()

    def get_int(key, default):
        return int(form.get(key, default))

    def get_float(key, default):
        return float(form.get(key, default))

    def get_bool(key, default):
        val = form.get(key)
        if val is None:
            return default
        return val.lower() in ("true", "1", "on", "yes")

    use_superpixels = get_bool("use_superpixels", defaults["use_superpixels"])

    return {
        "num_levels": max(2, profile.num_layers),
        "preprocess_method": form.get("preprocess_method", defaults["preprocess_method"]),
        "gaussian_kernel_size": get_int("gaussian_kernel_size", defaults["gaussian_kernel_size"]),
        "median_kernel_size": get_int("median_kernel_size", defaults["median_kernel_size"]),
        "bilateral_d": get_int("bilateral_d", defaults["bilateral_d"]),
        "bilateral_sigma_color": get_float("bilateral_sigma_color", defaults["bilateral_sigma_color"]),
        "bilateral_sigma_space": get_float("bilateral_sigma_space", defaults["bilateral_sigma_space"]),
        "postprocess_method": form.get("postprocess_method", defaults["postprocess_method"]),
        "morph_kernel_size": get_int("morph_kernel_size", defaults["morph_kernel_size"]),
        "min_region_size": get_int("min_region_size", defaults["min_region_size"]),
        "preserve_edges": get_bool("preserve_edges", defaults["preserve_edges"]),
        "use_superpixels": use_superpixels and SUPERPIXELS_AVAILABLE,
        "superpixel_region_size": get_int("superpixel_region_size", defaults["superpixel_region_size"]),
        "majority_window_size": get_int("majority_window_size", defaults["majority_window_size"]),
    }


def active_profiles():
    return ColorProfile.objects.filter(is_active=True).prefetch_related("layers")


def default_profile(profiles=None) -> ColorProfile | None:
    """The profile the studio pre-selects, as configured by the admin."""
    profiles = active_profiles() if profiles is None else profiles
    configured = SiteSettings.load().default_profile

    if configured and configured.is_active:
        return configured
    return profiles.first() if hasattr(profiles, "first") else (profiles[0] if profiles else None)


def resolve_profile(form) -> ColorProfile | None:
    """The profile the visitor selected; falls back to the configured default."""
    raw = form.get("profile_id")
    profiles = active_profiles()

    if raw:
        try:
            return profiles.get(pk=int(raw))
        except (ColorProfile.DoesNotExist, ValueError, TypeError):
            return None
    return default_profile(profiles)


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


# ----------------------------------------------------------- ready images ----

READY_SESSION_KEY = "ready_palette"


def clear_ready_state(request) -> None:
    """Forget any verified ready image (the visitor switched back to the studio)."""
    request.session.pop(READY_SESSION_KEY, None)


@require_POST
def ready_verify(request):
    """
    Check an already-layered image and, if it passes, stage it as an order.

    Nothing is processed here: the image is the customer's finished artwork.
    We only confirm it is built from a small set of solid colours, then snap
    away compression noise so the stored copy is exactly those colours.
    """
    site = SiteSettings.load()
    if not site.ready_images_enabled:
        return JsonResponse(
            {"ok": False, "error": "پذیرش تصاویر آماده در حال حاضر غیرفعال است."}, status=400
        )

    upload = request.FILES.get("image")
    if not upload or not upload.name:
        return JsonResponse({"ok": False, "error": "هیچ تصویری انتخاب نشده است."}, status=400)

    image_bytes = upload.read()
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return JsonResponse(
            {"ok": False, "error": "حجم تصویر بیش از حد مجاز است (حداکثر ۲۰ مگابایت)."},
            status=400,
        )

    try:
        Image.open(io.BytesIO(image_bytes)).verify()
    except Exception:
        return JsonResponse({"ok": False, "error": "فایل انتخاب‌شده یک تصویر معتبر نیست."}, status=400)

    try:
        report = verify_ready_image(image_bytes, **site.ready_image_rules())
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"بررسی تصویر ناموفق بود: {exc}"}, status=500)

    if not report["ok"]:
        clear_ready_state(request)
        return JsonResponse({
            "ok": False,
            "error": report["message"],
            "reason": report["reason"],
            "color_count": report["color_count"],
            "coverage": report["coverage"],
            "max_colors": site.ready_max_colors,
        }, status=400)

    # Store the artwork itself, plus a copy flattened onto the detected palette.
    session_id = uuid.uuid4().hex
    request.session["image_id"] = session_id
    store_original(session_id, image_bytes)

    snapped = prepare_ready_image(image_bytes, report["rgb"])
    store_result(session_id, snapped)

    request.session[READY_SESSION_KEY] = report["colors"]
    request.session["last_render"] = _config_fingerprint({"source": "ready"}, None)

    return JsonResponse({
        "ok": True,
        "message": report["message"],
        "colors": report["colors"],
        "shares": report["shares"],
        "color_count": report["color_count"],
        "coverage": report["coverage"],
        "result_url": bytes_to_display_data_url(snapped),
        "original_url": bytes_to_display_data_url(image_bytes),
        "sizing": sizing_payload(image_bytes),
        "session_id": session_id,
    })


# ----------------------------------------------------------------- pages ----

@ensure_csrf_cookie
@require_GET
def index(request):
    """The studio page. Deliberately open to anonymous visitors."""
    profiles = list(active_profiles())
    site = SiteSettings.load()
    selected = default_profile(profiles)

    context = {
        # Studio defaults are admin-configurable, not hardcoded.
        "default_config": site.render_defaults(),
        "profiles": profiles,
        "profiles_json": [profile.as_dict() for profile in profiles],
        "selected_profile_id": selected.id if selected else None,
        "sizing": sizing_payload(),
        "superpixels_available": SUPERPIXELS_AVAILABLE,
        "ready_enabled": site.ready_images_enabled,
        "ready_max_colors": site.ready_max_colors,
        "ai_helper": site.ai_helper(),
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

@login_required
@require_GET
def order_stl(request, pk: int):
    """
    Generate and download the 3D model for an order.

    Admin-only: turning an order into a printable plate is a production step,
    not something the customer does.
    """
    if not request.user.is_staff:
        raise Http404

    order = get_object_or_404(Order, pk=pk)
    if not order.result_image:
        raise Http404

    site = SiteSettings.load()
    colors = order.colors or (order.profile.color_list() if order.profile else [])
    if not colors:
        return HttpResponseBadRequest("این سفارش هیچ رنگ لایه‌ای ثبت‌شده ندارد.")

    try:
        with Image.open(order.result_image.path) as image:
            image.load()
            width_px, height_px = image.size

            width_mm, height_mm = _frame_size_mm(order, site, width_px / height_px)
            payload, stats = order_to_stl(
                image,
                colors=colors,
                layer_heights_mm=site.layer_heights_mm(len(colors)),
                width_mm=width_mm,
                height_mm=height_mm,
                max_resolution=site.stl_max_resolution,
                header=f"Photo Frame 2D order {order.pk}",
            )
    except (ValueError, OSError) as exc:
        return HttpResponseBadRequest(f"ساخت مدل سه‌بعدی ناموفق بود: {exc}")

    response = HttpResponse(payload, content_type="model/stl")
    response["Content-Disposition"] = f'attachment; filename="photo-frame-2d-order-{order.pk}.stl"'
    response["X-Model-Triangles"] = str(stats["triangles"])
    response["X-Model-Size-Mm"] = f"{stats['width_mm']}x{stats['height_mm']}x{stats['max_height_mm']}"
    return response


def _frame_size_mm(order: Order, site: SiteSettings, ratio: float) -> tuple:
    """
    Physical plate size in millimetres.

    Orders placed before frame sizing existed have no dimensions, so fall back
    to a default width that respects the configured limits and the image ratio.
    """
    if order.width_cm and order.height_cm:
        return float(order.width_cm) * 10, float(order.height_cm) * 10

    low, high = site.width_bounds_for_ratio(ratio)
    if low > high:
        raise ValueError("نسبت این تصویر با محدودهٔ اندازهٔ فعلی سازگار نیست.")

    width = min(max(Decimal("30"), low), high)
    height = site.height_for_width(width, ratio)
    return float(width) * 10, float(height) * 10


@require_GET
def get_config(request):
    site = SiteSettings.load()
    selected = default_profile()

    return JsonResponse({
        "defaults": site.render_defaults(),
        "engine_defaults": DEFAULT_CONFIG,
        "profiles": [profile.as_dict() for profile in active_profiles()],
        "default_profile_id": selected.id if selected else None,
        "sizing": sizing_payload(),
        "superpixels_available": SUPERPIXELS_AVAILABLE,
        "ready_images": {
            "enabled": site.ready_images_enabled,
            "max_colors": site.ready_max_colors,
        },
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
        clear_ready_state(request)
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

    # Two ways to reach an order: built in the studio, or a verified ready image.
    is_ready = (
        request.POST.get("source") == Order.SOURCE_READY
        and request.session.get(READY_SESSION_KEY)
    )

    profile = None
    if not is_ready:
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

    if is_ready:
        ready_colors = list(request.session[READY_SESSION_KEY])
        config = {"source": Order.SOURCE_READY, "num_levels": len(ready_colors)}
    else:
        ready_colors = None
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

            if is_ready:
                # The customer's own artwork, flattened onto its detected
                # palette when it was verified. Never re-processed.
                result_bytes = load_result(session_id)
                if result_bytes is None:
                    return JsonResponse(
                        {"ok": False, "error": "تصویر تأییدشده یافت نشد. لطفاً دوباره بارگذاری کنید."},
                        status=400,
                    )
                order_colors = ready_colors
            else:
                # Reuse the render the visitor is looking at; only redo the work
                # if the settings changed since the last preview.
                order_colors = profile.color_list()
                result_bytes = None
                if request.session.get("last_render") == _config_fingerprint(config, profile.id):
                    result_bytes = load_result(session_id)
                if result_bytes is None:
                    result_bytes = process_image_bytes(
                        original_bytes, colors=order_colors, **config
                    )

            order = Order(
                user=request.user,
                source=Order.SOURCE_READY if is_ready else Order.SOURCE_STUDIO,
                profile=profile,
                profile_name="" if is_ready else profile.name,
                num_layers=len(order_colors),
                colors=order_colors,
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
            "profile": order.palette_label,
            "source": order.source,
            "num_layers": order.num_layers,
            "size": order.size_label,
            "estimated_cost": order.estimated_cost,
            "estimated_cost_label": format_toman(order.estimated_cost),
        },
        "user": user_payload(request.user),
    })
