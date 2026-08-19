# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Persian, right-to-left web shop. A visitor uploads a photo, it is posterised
into a few flat colours using an admin-defined palette, they pick a frame size
and see an estimated price, and they place an order. An admin reviews it, sets
the final price, and exports it as a **3D STL plate** — one terrace per colour —
which gets printed and posted to the customer.

The directory is still named `Photo-Frame-2D` and is deliberately not renamed:
the virtualenv's shebangs and the systemd unit's `WorkingDirectory`,
`ExecStart` and `EnvironmentFile` all point at that absolute path. The product
itself is "Photo Frame 3D" / «قاب عکس سه‌بعدی» everywhere else.

## Commands

Everything runs through the project virtualenv. There is no `make`, no tox.

```bash
.venv/bin/python manage.py test                       # full suite (94 tests, ~60s)
.venv/bin/python manage.py test posterizer.tests.GalleryTests
.venv/bin/python manage.py test posterizer.tests.StlExportTests.test_stl_is_a_closed_manifold_solid
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations && .venv/bin/python manage.py migrate

./run.sh                                              # dev server, autoreload, DEBUG=1
sudo ./scripts/install.sh --skip-apt                  # apply changes to the live service
```

**After editing anything in `static/`, run `collectstatic` or the change will
not appear.** The live service runs with `DEBUG=0`, where WhiteNoise serves
`staticfiles/`, not `static/`:

```bash
PHOTO_FRAME_DEBUG=0 .venv/bin/python manage.py collectstatic --noinput
systemctl restart photo-frame-3d.service
```

Other scripts: `backup.sh`, `restore.sh`, `create-admin.sh`, `uninstall.sh`,
`make_logo.py` (rebuilds all brand assets from one image). See
`docs/OPERATIONS.md`.

## Language rule

The split is at the product boundary, not the file boundary:

- **Persian** — everything a user or admin reads: templates, admin verbose
  names and help text, API error messages, model choice labels. Pages are
  `lang="fa" dir="rtl"`, dates are Jalali via `posterizer/templatetags/jalali_tags.py`,
  and numerals shown to users are Persian (`to_persian_digits`).
- **English** — everything a developer or operator reads: `README.md`, `docs/`,
  `CHANGELOG.md`, code comments and docstrings, script output and `--help`,
  management command help.

`posterizer/tests.py` asserts on Persian UI strings, so it contains Persian by
necessity. Phone numbers and numeric form fields must accept Persian and Arabic
digits — `accounts/validators.py` and `posterizer/views.to_ascii_number()`
normalise them.

## Architecture

Three layers, deliberately dependency-light: SQLite, no Redis, no Celery, and
nginx is optional (gunicorn + WhiteNoise serve everything).

**`main.py`** is the posterisation engine and has no Django import. It also
works as a standalone CLI. Everything else imports `process_image_bytes` from it.

**`accounts/`** — the user is keyed on `phone` (`USERNAME_FIELD`), there is no
username, and `PhoneOrEmailBackend` lets people sign in with either. Auth is
JSON-only (`/api/auth/*`) because sign-in happens in a modal.

**`posterizer/`** — the studio, orders and admin. The modules worth knowing:

| Module | Responsibility |
|---|---|
| `images.py` | Every upload passes through `normalise_upload()` first — EXIF rotation, pixel cap, downscale |
| `ready.py` | Verifies a customer-supplied layered image really is built from solid colours |
| `stl.py` | Height map → watertight binary STL |
| `throttle.py` | Per-IP rate limiting for the CPU-heavy endpoints |
| `jalali.py` | Jalali dates, Persian digits, Toman formatting |

### Rules that must not be broken

**The server is the only source of truth for anything that costs money.** The
layer count comes from the chosen `ColorProfile`, the frame height is derived
from the image's aspect ratio, and the price is recomputed from those. A
tampered browser must not be able to change what gets built or what it costs.
There are tests for each of these; do not "simplify" them by trusting the form.

**Orders snapshot everything.** `profile_name`, `colors`, `config`, `num_layers`
and `price_per_cm2` are copied onto the `Order` at submission. Editing a palette
or a price must never alter an order already placed.

**Order images are private.** They are streamed by a permission-checked view,
never served off disk. The one exception is the *rendered* image of an order an
admin has flagged `in_gallery`; the customer's original photograph is never
public, whatever that flag says.

**Signing in must not lose the visitor's work.** `django.contrib.auth.login()`
cycles the session, so `accounts/views._login_preserving_session()` carries
`image_id` across explicitly, and the rotated CSRF token is returned in the
JSON response. There is a test for this; it protects the core UX promise.

## Traps this codebase has already hit

Each of these cost real debugging time and has a regression test.

**`(int16 - int16) ** 2` overflows.** A squared channel difference reaches
65025, which wraps negative in `int16`, so a nearest-colour `argmin` silently
returns the wrong palette entry. Colour matching in `stl.py` and `ready.py`
uses `int32`. This shipped once and corrupted STL heights.

**EXIF orientation is not cosmetic.** A phone stores a portrait photo as
landscape pixels plus a rotate tag. The aspect ratio decides the *physical
frame's dimensions*, so ignoring the tag means printing a landscape frame for a
portrait photo. `normalise_upload()` applies it before anything measures the
image — keep it that way.

**File size is the wrong limit for images.** A 63 MP photo compresses to about
1 MB. Cap *pixels*, and read dimensions from the header before decoding, or a
small file that expands to gigapixels gets decoded.

**A local-memory cache is per-worker.** gunicorn runs several workers, so
`locmem` would divide every rate limit by the worker count. `CACHES` is
filesystem-based on purpose.

**Rate limiting keys on IP, not session.** A session key does not exist until
the session is first saved, so a visitor's identity changes between their first
and second request and the first is never counted.

**STL meshes need two guarantees to be printable.** Walls are split at every
canonical layer height so corners cannot form T-junctions, and saddle points —
where two stacks touch along a single line — are filled before meshing.
`mesh_is_closed()` asserts every directed edge appears exactly once with one
reverse twin, which catches both closure and normal-orientation faults.

**Flex centring clips overflow in both directions.** `.canvas-area` centres
with auto margins, not `align-items`, and carries `min-height: 0` — without it
a flex item will not shrink below its content and the parent's `overflow:
hidden` silently cuts the top off.

**In RTL, an `auto-fill` grid packs to the right.** Empty tracks are kept, so
few items cluster in the first tracks — the right-hand edge. Use wrapping flex
with `justify-content: center` for centred rows.

**Django template `{# #}` comments are single-line only.** A multi-line one is
rendered to the page as literal text. Use `{% comment %}`.

**`format_html()` with no interpolation arguments raises `TypeError`.** Use
`mark_safe` for a static string.

## Front end

No framework. Three files: `static/js/auth.js` (a `window.PF` helper providing
CSRF-aware `post()`, toasts, the account menu and the auth modal),
`static/js/app.js` (the studio), and `static/css/style.css`.

The studio has two modes — build with our tool, or upload a ready-made layered
image — switched by a segmented control. `.studio-only` and `.ready-only`
elements are toggled by `setMode()`. Frame-size inputs deliberately carry **no
`name` attribute** so they stay out of `FormData`: changing the size must not
mark the render stale.

## Not in git, and why

`db.sqlite3`, `media/`, `uploads/`, `.env`, `backups/`, `cache/`,
`staticfiles/`, `.venv/`. The first four are the runtime state that
`scripts/backup.sh` packages into a single zip. `media/` holds real customers'
photographs.

Backup archives declare an `application` name in their manifest, and
`scripts/_restore.py` accepts both `photo-frame-3d` and the pre-rename
`photo-frame-2d` — do not tighten that or existing backups stop restoring.

## Known gaps

There is a full audit of what is missing for a real shop — no payment, no
delivery address on orders, no password reset or SMS, pricing blind to model
volume. Rather than rediscover them, read `docs/` and the audit list before
planning new work.
