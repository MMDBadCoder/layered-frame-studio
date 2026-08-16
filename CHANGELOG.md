# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/).

---

## [1.1.0] — 2026-08-16 (1405-05-26)

### Added — 3D model export (STL)
- `posterizer/stl.py`: turns an order's layered image into a terraced 3D plate
- One terrace per colour: layer 1 at height x, layer 2 at 2x, layer 3 at 3x, and so on
- `stl_layer_height_mm` — the value of x, editable in the admin panel
- `stl_invert_heights` — flip the direction (darkest layer becomes the tallest)
- `stl_max_resolution` — trade detail against file size
- Model footprint matches the ordered frame size exactly
- STL download button on the order list and on each order's page
- Admin-only access
- Watertight, manifold output: walls are split at the standard heights, and
  saddle points — which would otherwise join the solid along a single line and
  make it unprintable — are resolved

### Added — configurable render defaults
- Every studio default is now editable in the admin panel (smoothing method,
  kernels, cleanup method, minimum region size, edge preservation, and so on)
- `default_profile` — the colour profile the studio opens with
- These defaults replaced the hard-coded `DEFAULT_CONFIG` in `main.py`
- The user's own choices still take precedence over the defaults

### Changed
- Studio page title shortened from "قاب عکس دوبعدی — استودیو ساخت تصاویر لایه‌ای"
  to "قاب عکس دوبعدی" so it is fully visible in a browser tab
- Orders page title shortened to "سفارش‌های من" ("My orders")
- `/api/config` now also returns the configured defaults and the default profile

---

## [1.0.0] — 2026-08-16 (1405-05-26)

First complete release: studio, user accounts, ordering, pricing and
maintenance tooling.

### Added — frame size and price
- Singleton `SiteSettings` model for the size range and the price per square centimetre
- Frame size picker that preserves the original image's aspect ratio (slider plus two synced number boxes)
- Effective width range derived from the height limits and the image ratio
- Live cost estimate, always labelled "approximate", in the sidebar and the confirmation dialog
- `estimated_cost` stored on the order; admins can set `final_cost` after review
- Cost shown on the "My orders" page
- Full server-side validation: height and price are always recomputed on the server

### Added — maintenance tooling
- `scripts/install.sh` — complete idempotent install with a systemd service and a health check
- `scripts/uninstall.sh` — remove the service, keeping data by default
- `scripts/create-admin.sh` plus the `create_admin` management command
- `scripts/backup.sh` — pack the whole state into a zip with a manifest and checksum
- `scripts/restore.sh` — restore with an automatic safety snapshot
- `scripts/_common.sh` — shared shell helpers
- gunicorn + WhiteNoise for production serving without nginx
- `.env` support with automatic secret key generation

### Added — accounts and orders
- Custom user identified by mobile number, email and password (no username)
- Sign in with either mobile number or email; Persian and Arabic digits accepted
- Sign-in and registration in a modal, with no page reload — the rendered image survives
- Rate limiting on failed sign-in attempts
- Order submission with a confirmation dialog and an optional note
- A cap of 3 unreviewed orders per user, enforced inside a transaction
- "My orders" page with Jalali dates
- Private serving of order images

### Added — colour profiles
- `ColorProfile` and `ProfileLayer`, holding the layer count and each layer's colour
- Colour output instead of greyscale in the processing engine (`main.py`)
- Colour rows are kept in sync with the layer count automatically
- Five default palettes shipped as a data migration
- The "layer count" slider was replaced by a profile picker

### Added — admin panel
- Django admin panel, fully Persian and RTL
- Order management with thumbnails and single or bulk status changes
- Reviewer and review timestamp recorded automatically
- Profile management with a real colour picker
- Site settings management with a sample price table

### Changed
- Entire UI moved to Persian and `dir="rtl"` with the Vazirmatn font
- Jalali dates and Persian digits (`posterizer/jalali.py`, no new dependency)
- `main.py` now takes command-line arguments (it used a hard-coded path before)
- `opencv-python` → `opencv-python-headless` for headless servers

### Fixed
- The "apply changes" button stayed enabled forever: a client-side string was
  compared against server-side JSON and could never match. It now compares a
  snapshot of the settings that produced the current image.
- Multi-line template comments (`{# … #}`) leaking into the HTML output

### Security
- CSRF on every POST; a fresh token is returned after sign-in
- Server-side validation of layer count, dimensions and price
- `DEBUG=0` as the production install default
- Mode `600` on `.env`, and `.env` kept out of git

---

## [0.2.0] — Django rewrite

- Complete migration from Flask to Django, preserving look and behaviour exactly
- `main.py` kept as a standalone processing engine

## [0.1.0] — Initial version
- Flask application with greyscale processing and a single-page interface
