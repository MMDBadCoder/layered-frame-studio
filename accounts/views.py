"""JSON auth endpoints driving the sign-in / sign-up modal."""

from django.contrib.auth import login as auth_login
from django.contrib.auth import authenticate
from django.contrib.auth import logout as auth_logout
from django.core.cache import cache
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET, require_POST

from .forms import LoginForm, RegisterForm

# Session keys that must survive a sign-in, so that the image someone just
# built is still there after they authenticate.
PRESERVED_SESSION_KEYS = ("image_id", "last_render")

FAILED_LOGIN_LIMIT = 10
FAILED_LOGIN_WINDOW = 5 * 60  # seconds


def user_payload(user) -> dict:
    """Everything the front-end needs to render the account area."""
    from posterizer.models import Order

    return {
        "is_authenticated": True,
        "display_name": user.display_name,
        "phone": user.phone,
        "email": user.email,
        "is_staff": user.is_staff,
        "role": user.role_label,
        "unreviewed_orders": Order.objects.unreviewed_count(user),
        "max_unreviewed_orders": Order.MAX_UNREVIEWED,
    }


def anonymous_payload() -> dict:
    return {"is_authenticated": False}


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def _throttle_key(request) -> str:
    return f"login-attempts:{_client_ip(request)}"


def _is_throttled(request) -> bool:
    return cache.get(_throttle_key(request), 0) >= FAILED_LOGIN_LIMIT


def _record_failure(request) -> None:
    key = _throttle_key(request)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, FAILED_LOGIN_WINDOW)


def _clear_failures(request) -> None:
    cache.delete(_throttle_key(request))


def _login_preserving_session(request, user) -> None:
    """
    Sign the user in without dropping the work in progress.

    django.contrib.auth.login() cycles (or flushes) the session, which would
    otherwise throw away the id of the image the visitor just uploaded.
    """
    preserved = {key: request.session[key] for key in PRESERVED_SESSION_KEYS if key in request.session}
    auth_login(request, user)
    for key, value in preserved.items():
        request.session[key] = value


@require_GET
def status(request):
    """Used on page load to decide what the header shows."""
    if request.user.is_authenticated:
        return JsonResponse({"ok": True, "user": user_payload(request.user)})
    return JsonResponse({"ok": True, "user": anonymous_payload()})


@require_POST
def register(request):
    if request.user.is_authenticated:
        return JsonResponse({"ok": True, "user": user_payload(request.user)})

    form = RegisterForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "error": "لطفاً خطاهای فرم را برطرف کنید.",
                "errors": form.errors.get_json_data(escape_html=True),
            },
            status=400,
        )

    user = form.save()
    # The backend is unambiguous here, but be explicit so Django does not have
    # to guess which one authenticated this user.
    user.backend = "accounts.backends.PhoneOrEmailBackend"
    _login_preserving_session(request, user)
    _clear_failures(request)

    return JsonResponse({
        "ok": True,
        "user": user_payload(user),
        "csrf_token": get_token(request),
        "message": "حساب کاربری شما ساخته شد. خوش آمدید!",
    })


@require_POST
def login(request):
    if request.user.is_authenticated:
        return JsonResponse({"ok": True, "user": user_payload(request.user)})

    if _is_throttled(request):
        return JsonResponse(
            {
                "ok": False,
                "error": "تعداد تلاش‌های ناموفق زیاد بوده است. چند دقیقه بعد دوباره تلاش کنید.",
            },
            status=429,
        )

    form = LoginForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "error": "لطفاً خطاهای فرم را برطرف کنید.",
                "errors": form.errors.get_json_data(escape_html=True),
            },
            status=400,
        )

    user = authenticate(
        request,
        username=form.cleaned_data["identifier"],
        password=form.cleaned_data["password"],
    )

    if user is None:
        _record_failure(request)
        return JsonResponse(
            {"ok": False, "error": "شماره موبایل/ایمیل یا رمز عبور نادرست است."},
            status=401,
        )

    if not user.is_active:
        return JsonResponse(
            {"ok": False, "error": "این حساب کاربری غیرفعال شده است."},
            status=403,
        )

    _login_preserving_session(request, user)
    _clear_failures(request)

    return JsonResponse({
        "ok": True,
        "user": user_payload(user),
        # login() rotates the CSRF token, so hand the fresh one back.
        "csrf_token": get_token(request),
        "message": "خوش آمدید!",
    })


@require_POST
def logout(request):
    auth_logout(request)
    return JsonResponse({
        "ok": True,
        "user": anonymous_payload(),
        "csrf_token": get_token(request),
        "message": "از حساب کاربری خارج شدید.",
    })
