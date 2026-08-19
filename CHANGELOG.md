# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/).

---

## [1.2.0] — 2026-08-19

### Added — raised border on the 3D model
- The exported plate now carries a border around the picture, standing at the
  height of the tallest layer: seven layers at 2 mm gives a 14 mm surround
  regardless of what the picture reaches at its own edges.
- Thickness is a share of the picture's shorter side — default 3%, with a 3 mm
  floor so small frames still get something printable — both configurable in
  the site settings. Setting the percentage to 0 removes the border.
- The border is added outwards, so the ordered picture keeps its exact size and
  the finished plate grows by twice the thickness on each axis. The download
  reports the applied value in an `X-Model-Border-Mm` header, which can differ
  slightly from the requested one because thickness is quantised to whole grid
  cells.
- Implemented by padding the height map rather than emitting separate geometry,
  so the existing wall splitting, saddle repair and manifold guarantees apply to
  the border unchanged. Verified watertight for 4, 7 and 16-layer plates over
  both banded and noisy inputs.

### Added — project notes
- `CLAUDE.md` records what the code cannot state for itself: where the
  Persian/English boundary falls, the rules that must not be relaxed, and the
  traps this codebase has already paid for — the int16 overflow in colour
  matching, why EXIF orientation changes the physical frame's shape, why file
  size is the wrong limit for an image, and why a local-memory cache divides
  every rate limit by the worker count.

---

## [1.1.0] — 2026-08-19

### Fixed
- **Photos taken on a phone were rendered sideways, and the frame was ordered
  in the wrong shape.** A phone stores a portrait photo as landscape pixels
  plus an EXIF orientation tag; the tag was ignored everywhere. Because the
  aspect ratio decides the dimensions of the physical frame, a customer
  ordering a 20×30 portrait would have received a 30×20 landscape plate.
  Orientation is now applied on upload, before anything measures the image.

### Added — upload limits and throttling
- Resolution cap (40 MP) with the actual dimensions in the refusal message, and
  automatic downscaling to 1.5 MP before processing. A 12 MP photo went from
  not finishing inside the 300-second worker timeout to about 2 seconds.
- Dimensions are read from the image header before any pixels are decoded, so a
  small file that expands to gigapixels is refused rather than decoded.
- Per-IP rate limiting on both render endpoints. They need no account and are
  CPU-bound, which made them the cheapest way to take the site down.
- The cache backing the limits is filesystem-based rather than local memory,
  because each gunicorn worker would otherwise keep its own counter. This also
  fixes the pre-existing sign-in limiter, which had the same flaw.
- Worker count now follows the core count; rendering is CPU-bound, so the usual
  2×cores+1 rule only added contention.

### Added — homepage gallery
- Admins mark finished orders for display on the landing page, individually or
  in bulk, with an optional caption and ordering.
- Flagging publishes **only** the rendered layered image. The customer's
  original photograph stays private, and no name or contact detail is shown.

### Fixed — studio layout
Adding the gallery made the canvas taller than it had ever been, which exposed
three layout faults that had been latent:

- **The top of the upload box could not be reached.** `.canvas-area` is a flex
  item with no `min-height`, and a flex item will not shrink below its content,
  so the canvas grew past the viewport and `overflow: hidden` on its parent cut
  the excess off — its own `overflow: auto` never engaged. It also centred with
  `align-items`, and centred flex content overflows in both directions at once,
  putting the top above the scroll origin. Centring is now done with auto
  margins, which collapse to zero when space runs out.
- **Gallery tiles sat against the right edge** instead of centred. The strip
  used an `auto-fill` grid, which keeps its empty tracks, so a few tiles packed
  into the first ones — the right-hand side in an RTL document. Wrapping flex
  centres every row, including the last.
- **The canvas scrollbar was the browser default**, a heavy light slab on a
  dark interface, and the only scrollable area in the app not already styled.
  All of them now share one slim, recessed treatment.

The upload box's width is also bounded by `58vh` now, so it scales with the
window instead of forcing a scroll on shorter screens.

---

## [1.0.1] — 2026-08-18

### Changed
- The product is called **Photo Frame 3D** everywhere. The Persian UI was
  renamed in 0.5.0; this completes the sweep across the README, the `docs/`
  folder, the maintenance scripts, code comments, the systemd unit, the STL
  file header and the names of downloaded files. It builds a 3D layered frame,
  not a flat one.
- The systemd unit is now `photo-frame-3d.service`. `install.sh` and
  `uninstall.sh` retire a leftover `photo-frame-2d.service` first, so a machine
  installed before the rename does not end up running two units on one port.
- Backup archives declare `photo-frame-3d` and are named accordingly.

### Compatibility
- **Archives made before the rename still restore.** They declare the old
  application name, which `restore.sh` would otherwise reject as belonging to a
  different program; both names are accepted.
- Backup retention matches either naming scheme, so older archives are still
  pruned by `--keep`.
- Documented cron examples use a placeholder path instead of a hardcoded one.
  The project directory itself is deliberately not renamed: the virtualenv's
  shebangs and the systemd unit's paths point at it.

---

## [1.0.0] — 2026-08-18

First stable release.

A Persian, right-to-left studio that turns a photograph into a layered poster
image, takes orders for a physical frame at a chosen size and price, and
exports each order as a printable 3D plate.

**What it does**
- Two ways to reach an order: build the image in the studio with an
  admin-defined colour palette, or upload one already made elsewhere, which is
  verified to be built from solid colours before it is accepted.
- Frame sizing that always follows the photo's aspect ratio, with an
  approximate price shown live and a final price set by an admin after review.
- Accounts keyed on a mobile number, sign-in in a modal so a rendered image is
  never lost, and a cap of three unreviewed orders per customer.
- STL export: one terrace per colour, darkest tallest, watertight and
  manifold with outward-facing normals.
- A fully Persian admin panel covering orders, palettes, prices, studio
  defaults, ready-image rules and 3D parameters.

**Operating it**
- `scripts/install.sh` sets up a fresh Ubuntu server in one idempotent command
  and runs it under systemd.
- `scripts/backup.sh` and `scripts/restore.sh` move the entire state — database,
  order images, live session renders and the secret key — as a single zip.

**Guarantees covered by the test suite (78 tests)**
- Layer count, frame height and price are always recomputed server-side; a
  tampered browser cannot change what is built or what it costs.
- The exported mesh is closed, consistently oriented, and solid from the base
  to the top of every column.
- Editing a palette or a price never alters an order already placed.

---

## [0.5.0] — 2026-08-18

### Added
- Brand mark and a full favicon set (SVG, 16/32/180px), wired into both pages
  and the admin panel; the site previously had no favicon at all.
- `scripts/make_logo.py` rebuilds every brand asset from a single source image:
  unmixes the alpha instead of colour-keying it, re-emits rectangular marks as
  exact vector geometry, and snaps colours to the site accent.

### Changed
- The Persian UI name is now «قاب عکس سه‌بعدی» — the product makes a 3D layered
  frame, not a flat one.
- The AI helper prompt shown beside the ready-image upload is admin-editable
  and ships with the supplied wording.

### Fixed
- The ready-image upload box centred its contents correctly: a lone flex item
  is sized to its content, which in RTL pushed the text against the right edge.

---

## [0.4.1] — 2026-08-18

### Fixed
- **The 3D model was built upside down.** The darkest colour received the
  shortest step and the lightest the tallest, which is backwards for a layered
  frame: dark areas are the deep ones. Reported after a real print.
- `stl_invert_heights` (default False) is replaced by `stl_dark_is_tallest`
  (default True). The old flag was also confusingly named — a boolean called
  "invert" whose default is the inverted state. Existing installations are
  moved to the corrected behaviour by migration 0008; the previous value is
  deliberately not carried over, because it was a wrong default rather than a
  considered choice.
- Added an end-to-end test that measures the exported mesh itself, not just the
  height table, and asserts the darkest band is the tallest.

---

## [0.4.0] — 2026-08-17

### Added — ready-made images (second order path)
- `posterizer/ready.py`: verifies that a customer-supplied image really is built
  from a small set of solid colours, and detects its palette
- Greedy colour clustering with an artefact-absorbing merge pass, so the same
  artwork is read identically whether it arrives as a clean PNG or a JPEG
- Gradients, photographs and near-single-colour images are rejected with a
  specific Persian explanation
- `POST /api/ready/verify`; the stored image is snapped onto the detected
  palette so 3D export stays exact
- Mode switch on the studio page between building an image and uploading one
- Orders record their `source`; shown in the admin and on the orders page
- Admin settings for the acceptance rules, and an editable AI helper card
  (model name, link and a copyable prompt) shown beside the upload area

### Fixed
- **Colour matching overflowed `int16`.** Squared channel differences reach
  65025, which wraps negative in `int16`, so `argmin` could pick a completely
  wrong palette entry — a pixel exactly equal to layer 0 was mapped to layer 3.
  This affected the STL exporter's height assignment. Both the exporter and the
  new detector now use `int32`.
- `format_html()` called with no interpolation arguments raised `TypeError` on
  modern Django, crashing the order list for any order with an empty palette

---

## [0.3.0] — 2026-08-16 (1405-05-26)

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

## [0.2.0] — 2026-08-16 (1405-05-26)

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

## [0.1.0] — Django rewrite

- Complete migration from Flask to Django, preserving look and behaviour exactly
- `main.py` kept as a standalone processing engine

## [0.0.1] — Initial version
- Flask application with greyscale processing and a single-page interface
