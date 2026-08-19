"""
Rate limiting for the expensive public endpoints.

Rendering an image is CPU-bound and needs no account, which makes it the
cheapest way to take the site down — deliberately or by a stuck retry loop.
Sign-in already had a limiter; rendering did not.

Counts live in the shared filesystem cache rather than local memory, because
gunicorn runs several worker processes and a per-process counter would make
every limit N times looser than it looks.
"""

from django.conf import settings
from django.core.cache import cache

DEFAULT_LIMIT = 20
DEFAULT_WINDOW = 300


def _limits() -> tuple:
    """Read at call time, not import time, so the values stay overridable."""
    return (
        getattr(settings, "RENDER_RATE_LIMIT", DEFAULT_LIMIT),
        getattr(settings, "RENDER_RATE_WINDOW", DEFAULT_WINDOW),
    )


def client_key(request, bucket: str) -> str:
    """
    Identify the caller by IP.

    Deliberately not the session: a session key does not exist until the
    session is first saved, so the identity would change between a visitor's
    first and second request and the first one would never be counted. It is
    also the weaker signal — anyone abusing the endpoint can simply drop the
    cookie, while the address is what actually costs us CPU.

    Visitors behind one NAT therefore share an allowance. The limit is set
    high enough that ordinary use never reaches it.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "unknown")
    return f"throttle:{bucket}:{ip}"


def check(request, bucket: str = "render") -> tuple:
    """
    Count this request against the caller's allowance.

    Returns (allowed, retry_after_seconds). The counter is only created on the
    first hit of a window, so the window slides forward from that first request
    rather than being reset by every subsequent one.
    """
    limit, window = _limits()
    key = client_key(request, bucket)
    used = cache.get(key)

    if used is None:
        cache.set(key, 1, window)
        return True, 0

    if used >= limit:
        return False, window

    try:
        cache.incr(key)
    except ValueError:          # expired between the get and the incr
        cache.set(key, 1, window)
    return True, 0
