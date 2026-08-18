# Architecture — Photo Frame 2D

---

## 1. Overview

```
Browser (no JS framework)
   │  fetch + FormData + X-CSRFToken
   ▼
gunicorn ──► Django 6 ──► SQLite (db.sqlite3)
   │            │
   │            ├─► main.py  ─► OpenCV / NumPy / scikit-image
   │            └─► media/   ─► order images (private)
   │
   └─► WhiteNoise ─► staticfiles/
```

No side services are required: no Redis, no Celery, no PostgreSQL, and nginx is
optional. That is deliberate — maintenance and backups have to stay simple.

---

## 2. Project layout

```
photoframe/          Django project: settings, urls, wsgi, asgi
accounts/            Custom user and authentication
  models.py          User keyed by mobile number instead of a username
  backends.py        Sign in with mobile number or email
  validators.py      Persian digit and mobile number normalisation
  forms.py           Sign-in and registration forms
  views.py           JSON endpoints used by the modal
  management/commands/create_admin.py
posterizer/          Studio, profiles, orders
  models.py          SiteSettings, ColorProfile, ProfileLayer, Order
  views.py           Pages + processing/order APIs + STL download
  admin.py           Persian admin panel
  stl.py             3D model generation from the layered image
  ready.py           verification of customer-supplied layered images
  jalali.py          Jalali dates, Persian digits, Toman formatting
  templatetags/      jalali, toman, cm and fa_digits filters
  management/commands/cleanup_uploads.py
main.py              Image processing engine (independent of Django)
templates/           base, index, orders + partials
static/              style.css, auth.js, app.js
scripts/             install, uninstall, create-admin, backup, restore
```

---

## 3. Data model

```
User (accounts)
 ├─ phone (unique, USERNAME_FIELD)
 ├─ email (unique)
 ├─ is_staff  → admin
 └─ is_superuser → superuser

SiteSettings (singleton, pk=1)
 ├─ size: min/max_width_cm, min/max_height_cm
 ├─ price: price_per_cm2, cost_rounding
 ├─ studio defaults: default_profile, default_preprocess_method,
 │    default_*_kernel_size, default_postprocess_method, default_min_region_size,
 │    default_preserve_edges, default_use_superpixels, …
 ├─ 3D: stl_layer_height_mm, stl_invert_heights, stl_max_resolution
 ├─ ready images: ready_images_enabled, ready_max_colors, ready_min_coverage,
 │    ready_min_layer_share
 └─ AI helper: ai_helper_enabled, ai_helper_model_name, ai_helper_url, ai_helper_prompt

ColorProfile
 ├─ name, description, num_layers, is_active, sort_order
 └─ layers → ProfileLayer(index, color)

Order
 ├─ user → User
 ├─ profile → ColorProfile (SET_NULL)
 ├─ source: studio | ready
 ├─ snapshot: profile_name, num_layers, colors, config
 ├─ size: width_cm, height_cm, area_cm2
 ├─ price: price_per_cm2, estimated_cost, final_cost
 ├─ images: result_image, original_image
 └─ review: status, admin_note, reviewed_by, reviewed_at
```

### Why snapshot?
An order must show forever exactly what the customer ordered. If an admin later
changes a profile's colours or the price per cm², existing orders must not
change. That is why the profile name, colours, settings and price are copied
onto the order itself.

---

## 4. Endpoints

| Path | Method | Description |
|---|---|---|
| `/` | GET | Studio (public) |
| `/orders/` | GET | My orders (sign-in required) |
| `/orders/<id>/image/<kind>/` | GET | Order image (owner or admin) |
| `/orders/<id>/stl/` | GET | 3D model download (admin only) |
| `/api/config` | GET | Defaults, profiles, size range |
| `/api/process` | POST | Process an image → data URL + size range |
| `/api/ready/verify` | POST | Verify a ready-made image and stage it for ordering |
| `/api/orders/create` | POST | Place an order |
| `/api/auth/status` | GET | Sign-in status |
| `/api/auth/login` | POST | Sign in |
| `/api/auth/register` | POST | Register |
| `/api/auth/logout` | POST | Sign out |
| `/admin/` | — | Admin panel |

Every POST requires the `X-CSRFToken` header. Error responses have the shape
`{"error": "<Persian message>"}`, and auth responses `{"ok": bool, "errors": {...}}`.

---

## 5. Image processing pipeline

```
image bytes
   ↓ Pillow → greyscale array
   ↓ pre-processing (gaussian / median / bilateral)
   ↓ quantise to N evenly spaced levels (N comes from the profile)
   ↓ post-processing (median / morphology / connected components / majority)
   ↓ map each level to its layer colour (256×3 lookup table)
colour PNG
```

`main.py` has no dependency on Django and can be used on its own.

---

## 5.5 3D model generation (`posterizer/stl.py`)

```
the order's layered image
   ↓ downscale with nearest neighbour (no interpolation, so no new colours appear)
   ↓ map every pixel to the closest palette colour → layer index map
   ↓ resolve saddle points (resolve_saddles)
   ↓ index → height (layer n → n × base height)
   ↓ build the mesh: top surface + floor + walls
binary STL
```

### The two subtleties that make the mesh printable

**1. Splitting walls at the standard heights.** Where four cells of differing
heights meet, the walls around that corner span different height intervals. If
each wall were a single rectangle, the edges would not line up exactly and
would create T-junctions. The fix: every wall is split at all possible heights
(there are as many of them as there are layers).

**2. Resolving saddle points.** In the 2×2 block below

```
A B
C D
```

if one diagonal is strictly higher than the other, then at every horizontal
slice between the two the cross-section becomes two squares touching at a
single point — the solid pinches to a line and cannot be printed.
`resolve_saddles` raises the lower corner to fill that pinch. Because it only
ever raises, the loop is monotonic and terminates.

The top surface is deliberately **not** merged into wide strips: merging would
create T-junctions against the single-cell walls.

The `mesh_is_closed` test checks that every directed edge appears exactly once
and its reverse exactly once — which guarantees both closure and consistent
normal orientation.

### Temporary storage
- `uploads/<id>.bin` — the session's original image
- `uploads/<id>.result.png` — the most recent render

When an order is placed, the cached file is reused if the settings match the
last render; otherwise the image is reprocessed. That guarantees the order is
exactly what the user saw.

---

## 5.6 Ready-image verification (`posterizer/ready.py`)

```
uploaded image
   ↓ downscale (nearest neighbour, max 700 px)
   ↓ greedy clustering around the most frequent colours (tolerance 18)
   ↓ merge clusters below the layer-share threshold into the nearest layer
   ↓ judge: layer count ≤ limit, coverage ≥ threshold, at least 2 layers
   ↓ (on success) snap the full-resolution image onto the detected palette
verified artwork + palette
```

The merge step runs **before** the layer count is judged. Judging raw clusters
would reject a clean four-colour design purely for having anti-aliased or
JPEG-compressed edges, which produce a long tail of tiny clusters along every
boundary.

Squared colour distances are computed in `int32`. In `int16` a squared channel
difference (up to 65025) wraps negative, and the nearest-colour search then
returns an arbitrary layer — the same bug previously affected the STL exporter.

---

## 6. Key technical decisions

| Decision | Why |
|---|---|
| **SQLite** | One file, trivial backups, plenty for this traffic level |
| **Mobile number instead of username** | Iranian audience; a username carries no meaning here |
| **Database-backed sessions** | Sessions can be invalidated on sign-out |
| **Modal instead of a sign-in page** | The rendered image must not be lost (principle 2 in the PRD) |
| **Django admin panel** | Persian and RTL out of the box, free user and permission management |
| **WhiteNoise** | Removes the need for nginx to get started |
| **No JS framework** | Three plain files; easier to maintain later |
| **No hashed static filenames** | That would need a manifest; forgetting collectstatic must not cause a 500 |
| **Server-side computation** | Layer count, height and price are never taken from the browser |

---

## 7. Security

- **CSRF** on every POST; a fresh token is returned after sign-in
- **Sign-in rate limiting**: 10 failed attempts per IP in 5 minutes
- **Private images**: served through a view with an ownership check, not directly
- **Session preservation on sign-in**: `image_id` is carried over explicitly
- **Server-side validation** of layer count, size and price
- **`.env` with mode 600**, kept out of git
- **`DEBUG=0`** is the `install.sh` default

### Known limitations
- Plain HTTP, no TLS — production deployments must sit behind nginx with HTTPS
- The service runs as the project directory's owner (on this server: root)
- `ALLOWED_HOSTS = ["*"]`

---

## 8. Tests

```bash
.venv/bin/python manage.py test
```

56 tests in `posterizer/tests.py`:

| Class | Coverage |
|---|---|
| `PublicStudioTests` | Guest access, colours, input validation |
| `AuthTests` | Registration, sign-in, **image survival across sign-in** |
| `OrderTests` | Submission, the 3-order quota, image privacy |
| `FrameSizeAndCostTests` | Ratio, range, price, anti-tampering |
| `RenderDefaultsTests` | Configurable defaults and user-choice precedence |
| `StlExportTests` | Layer heights, dimensions, **watertightness**, access control |
| `ColorProfileTests` | Layer syncing, inactive profiles |
| `ReadyImageTests` | Palette detection, rejection, ordering, STL, UI |
| `PageTitleTests` | Page title length |
| `AdminPanelTests` | Access, status changes, bulk actions |

Test assertions match the Persian UI strings on purpose — the UI is Persian, so
the assertions have to be too.
