# Feature reference — Photo Frame 2D

The exact behaviour of every feature, for future reference. Each one is covered
by an automated test in `posterizer/tests.py` (56 tests).

Persian strings quoted below are the literal UI text, so you can find them in
the templates and the tests.

---

## 1. The render studio

### 1.1 Image upload
- Click the upload area or drag and drop a file
- JPG, PNG and WebP formats
- 20 MB maximum → message: "حجم تصویر بیش از حد مجاز است (حداکثر ۲۰ مگابایت)."
- Non-image file → "فایل انتخاب‌شده یک تصویر معتبر نیست."
- The original image is kept on disk, so changing settings does not require a re-upload

### 1.2 Colour profile
- The user picks **exactly one** of the active profiles
- The palette is previewed as a colour strip below the picker
- The layer count comes from the profile — the user cannot change it
- A tampered `num_levels` sent from the browser is **ignored**

### 1.3 Processing parameters
| Section | Options |
|---|---|
| Pre-processing | None, gaussian blur, median filter, bilateral (edge preserving) |
| Post-processing | None, median filter, morphology, connected components, majority filter |
| Advanced | Superpixels (needs full OpenCV; disabled with an explanation when missing) |

A method's fields are shown only while that method is selected.

### 1.4 The "apply changes" button
- Enabled only when the current settings differ from the ones that produced the current image
- The helper text has three states: processing / settings changed / settings in sync
- An order always records the settings of the **displayed image**, not the live form

### 1.5 Download
The layered image as a PNG named `photo-frame-2d.png`.

---

## 2. Frame size and price

### 2.1 The ratio rule
The frame's aspect ratio **always** equals the original image's aspect ratio.

```
height = width ÷ (image width ÷ image height)
```

### 2.2 Effective range
The height limits also narrow the width range:

```
effective min width = max(min width, min height × ratio)
effective max width = min(max width, max height × ratio)
```

Example with a 10–100 cm range:

| Image | Ratio | Allowed width |
|---|---|---|
| 1413×1766 (portrait) | 0.80 | 10 to 80 |
| 1766×1413 (landscape) | 1.25 | 12.5 to 100 |
| 800×800 (square) | 1.00 | 10 to 100 |
| 4000×500 (panorama) | 8.00 | 80 to 100 |

If the effective minimum exceeds the effective maximum, no size is possible and
an appropriate message is shown.

### 2.3 User interface
- One slider and two number boxes (width and height) that update each other
- Persian digits are accepted in the inputs (`۶۰` = `60`)
- The range is clamped on blur, so typing is not disrupted
- Out of range → an error message, and the order button is disabled

### 2.4 Price
```
approximate cost = area (cm²) × price per cm²
```
- Rounded to the nearest multiple of the "cost rounding" setting (default 1000 Toman)
- **Always** labelled "تقریبی" ("approximate")
- Shown live in the sidebar and again in the confirmation dialog
- The price at submission time is snapshotted onto the order; later price changes do not affect existing orders

**Both height and price are recomputed on the server.** Sending an arbitrary
height or amount from the browser has no effect.

---

## 3. User accounts

### 3.1 Registration
- Name (optional), mobile number, email, password, password confirmation
- Mobile number: `09xxxxxxxxx`; the `+98`, `0098`, `98` and `9xx…` forms are also accepted and normalised
- Persian and Arabic digits are converted to Latin
- Email and mobile number are unique
- Django's password validation is enabled (at least 8 characters, not purely numeric, not a common password, not similar to the email)

### 3.2 Sign-in
- With **either** the mobile number or the email
- After 10 failed attempts from one IP, a 5-minute lockout

### 3.3 Signing in without losing work
This is the single most important UI rule:
- Sign-in and registration happen in a modal on the same page
- The page never reloads
- The image id is carried over explicitly in the session (Django rotates the session key on login)
- A fresh CSRF token is returned to the browser after sign-in
- Dismissing the modal leaves the image untouched

---

## 4. Orders

### 4.1 Submission
1. The user clicks "ثبت سفارش" ("place order")
2. If not signed in → the sign-in modal (the image is preserved)
3. Confirmation dialog: preview, profile, layer count, size, approximate cost, quota, warning, optional note
4. Confirm → submitted

### 4.2 The 3-order quota
- At most 3 orders with status "pending review" or "under review"
- The check runs inside a transaction, so two fast clicks cannot slip past the quota
- Reviewing an order frees a slot

### 4.3 Stored contents
Final image, original image, profile name, layer count, colours, processing
settings, width, height, area, price per cm², estimated cost, user note.

All snapshotted: editing or deleting a profile does not change existing orders.

### 4.4 The "My orders" page
Image, order number, profile, layer count, size, Jalali date, colour-coded
status, cost (approximate or final), admin note, download button.

### 4.5 Image privacy
Images are served from `/orders/<id>/image/<kind>/` and only to the order's
owner and to admins. The `media/` directory is not directly reachable.

---

## 4.5 3D model export (STL)

An admin can generate an STL file from any order, for 3D printing or laser
cutting.

### The height rule
Every palette colour becomes a terrace with its own height:

```
layer 1 → x mm
layer 2 → 2x mm
layer 3 → 3x mm
…
```

`x` is the "layer height" setting in the site settings (default 2 mm).

With the defaults, layer 1 is the **darkest** colour, so dark areas end up
shortest and light areas tallest. If you want the opposite, enable
**"وارونه کردن ارتفاع لایه‌ها"** ("invert layer heights") so the darkest layer
becomes the tallest.

### Dimensions
- The plate's width and length match the ordered frame size exactly (cm → mm)
- Older orders without a size fall back to a default size inside the allowed range
- Total height = layer count × layer height

### Output quality
- **Resolution**: the longest side is divided into `stl_max_resolution` cells
  (default 400). A larger number means more detail and a heavier file. For a
  30 cm frame, 400 cells means roughly 0.75 mm per cell — about the nozzle size
  of a typical printer.
- **Format**: binary STL
- **Watertight**: the output is a closed manifold solid. Two guarantees make
  that possible:
  1. Every wall is split at all standard heights, so no T-junctions appear at
     corners.
  2. "Saddle" points — where two columns meet along a single line and cannot be
     printed — are filled before the model is built. On real posterised images
     this correction touches less than a few percent of the cells.
- **Normals** face outward (the computed volume is positive).

### Access
Admins only. Regular users and guests get a 404.

Path: `/orders/<id>/stl/` — the download button appears on the order list and
on each order's page.

---

## 5. Admin panel

The Django admin panel, in Persian and RTL.

### 5.1 Orders
- List: number, image, user, profile, layers, size, cost, status, Jalali date
- Status can be changed inline in the list
- Bulk actions: under review / approve / reject
- Order page: both images with download links, settings table, palette, cost breakdown
- Recording the "final cost" and the "admin note"
- Reviewer and time recorded automatically
- Creating an order by hand is disabled

### 5.2 Colour profiles
- Add / edit / deactivate
- Set the layer count; colour rows are created, removed and reordered automatically on save
- A real colour picker per layer
- Display ordering

### 5.3 Site settings
One page with four sections:

**Frame size range** — minimum/maximum width and height

**Pricing** — price per square centimetre, cost rounding, and a sample price
table that updates with the current settings

**Render defaults** — exactly what the user sees when the landing page opens:
- Default colour profile
- Smoothing method and its parameters (gaussian kernel, median kernel, bilateral diameter and sigmas)
- Cleanup method and its parameters (morphology kernel, minimum region size, majority window)
- Edge preservation, superpixels and superpixel region size

These are only a **starting point**; the user can change any of them. If the
default profile is deactivated, the system falls back to the first active one.

**3D export (STL)** — layer height, direction inversion, maximum resolution,
and a preview of the layer heights under the current settings

### 5.4 Users
List with role, order count and unreviewed count; promotion to admin.

---

## 6. Maintenance tooling

| Script | Key property |
|---|---|
| `install.sh` | Idempotent, runnable from anywhere, systemd, health check |
| `uninstall.sh` | Removes the service; data is kept by default |
| `create-admin.sh` | Interactive or flag-driven; promotes an existing user without touching their orders |
| `backup.sh` | Zip containing db + media + uploads + .env with a manifest and checksum |
| `restore.sh` | Validation, automatic safety snapshot, service stop/start, migrations |
| `manage.py cleanup_uploads` | Deletes stale temporary files |

---

## 7. Not implemented (future requests)

- Online payment
- SMS notification on order status changes
- Automatic password recovery
- Bulk STL download of several orders in one zip
