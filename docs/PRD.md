# Product Requirements Document (PRD) — Photo Frame 3D

> For release v1.0.0 — last updated 2026-08-18 (27 Mordad 1405)

---

## 1. Product summary

Photo Frame 3D is a Persian web application that converts a user's photograph
into an image made of a limited number of "colour layers" — exactly what is
needed to build a physical multi-layer frame out of wood, acrylic or cardboard.
The user sees the result live, chooses a frame size, sees an approximate price
and places an order. Admins review orders and set the final price.

### The problem it solves

Someone ordering a multi-layer frame has no idea what their photo will look
like once it has been layered, or what it will cost. The result is a lot of
back-and-forth between customer and workshop. This product hands the customer
an accurate preview and a price estimate up front.

### Audience

- **End user**: Persian-speaking, usually on a phone, not technical.
- **Admin**: the workshop owner or an operator, who reviews orders and sets prices.

---

## 2. Design principles (foundational decisions)

These are the rules every later decision has to stay consistent with:

| # | Principle | Rationale |
|---|---|---|
| 1 | **Sign-in is never mandatory** | The user must be able to try the product before committing to anything. The landing page must never force a login. |
| 2 | **The user's work is never lost** | Signing in happens in a modal; the page does not reload and the rendered image survives. |
| 3 | **The whole UI is Persian and RTL** | The audience is Persian-speaking. No English string may ever be shown to a user; dates are Jalali and digits are Persian. |
| 4 | **The server is the only source of truth** | Layer count, frame height and price are all computed server-side. Tampering with the browser must not change the price or the output. |
| 5 | **Easy to maintain** | Single-file SQLite, no side services. A backup must be a single zip file. |

---

## 3. Roles and permissions

| Role | Technical definition | Capabilities |
|---|---|---|
| Guest | Not authenticated | Upload a photo, process it, download the result, see the approximate price |
| User | `is_staff=False` | All of the above + place orders + view their orders and costs |
| Admin | `is_staff=True` | Access to the admin panel |
| Superuser | `is_superuser=True` | Full access, including creating and deleting admins |

Every user registers with a **mobile number, an email address and a password**.
Sign-in accepts either the mobile number or the email.

---

## 4. Functional requirements

### 4.1 Studio (landing page)

| ID | Requirement |
|---|---|
| S1 | Upload an image by click or drag-and-drop; 20 MB maximum |
| S2 | Select **exactly one** colour profile from the active profiles |
| S3 | Adjust the pre-processing and post-processing parameters |
| S4 | Show the original and the layered image side by side |
| S5 | The "apply changes" button is enabled only when the settings differ from the current result |
| S6 | Download the rendered image |

### 4.2 Colour profiles

| ID | Requirement |
|---|---|
| P1 | Each profile has a name, description, layer count (2 to 16) and a colour per layer |
| P2 | **The layer count is set by admins only** — the user does not choose it |
| P3 | Layer 0 is the darkest region, the last layer the lightest |
| P4 | Inactive profiles are not shown to users |
| P5 | Editing or deleting a profile must not corrupt existing orders (the data is snapshotted onto the order) |

### 4.3 Size and price

| ID | Requirement |
|---|---|
| Z1 | Admins set the minimum and maximum frame **width** and **height** |
| Z2 | The frame's aspect ratio **always** equals the original image's aspect ratio |
| Z3 | The user picks the width; the height is derived automatically (and vice versa) |
| Z4 | Both dimensions must fall inside the allowed range; the height limits also narrow the width range |
| Z5 | If the image ratio fits no allowed size at all, show a clear message |
| Z6 | Approximate cost = area (cm²) × price per cm² (set by admins) |
| Z7 | The amount is **always** labelled "approximate" |
| Z8 | After review, an admin can record a "final cost" |
| Z9 | The user sees their order's cost on the "My orders" page |

### 4.4 Orders

| ID | Requirement |
|---|---|
| O1 | Placing an order requires sign-in; sign-in happens in a modal |
| O2 | Before submitting, show a confirmation dialog with the preview, size, price and a warning |
| O3 | Each user may have at most **3 unreviewed orders** |
| O4 | An order contains: final image, original image, profile, colours, settings, size, price |
| O5 | Statuses: pending review, under review, approved, rejected |
| O6 | "Unreviewed" means status pending or under review |
| O7 | Order images are private: the order's owner and admins only |

### 4.5 3D model export

| ID | Requirement |
|---|---|
| T1 | An admin can generate and download an STL file from any order |
| T2 | One terrace per colour, at consecutive multiples of the base height x |
| T3 | The value of x ("layer height") is editable in the admin panel |
| T4 | The darkest colour is the tallest by default; the direction can be flipped |
| T5 | The plate's footprint equals the ordered frame size |
| T6 | The model resolution is configurable (detail vs. file size) |
| T7 | The output must be a closed, manifold, printable solid |
| T8 | Admin-only access |

### 4.6 Render defaults

| ID | Requirement |
|---|---|
| D1 | Admins set every studio default value |
| D2 | The user sees exactly those values when the landing page opens |
| D3 | The user may change any of them; their choice wins |
| D4 | Admins also set the default colour profile |
| D5 | If the default profile is deactivated, the first active profile takes over |

### 4.7 Ready-made images

| Code | Requirement |
|---|---|
| R1 | A customer can order an image they built with another tool, without using the studio |
| R2 | Both paths are offered on the same page via a mode switch |
| R3 | An uploaded image is accepted only if it is built from solid colours |
| R4 | The layer palette is detected from the image; no colour profile is involved |
| R5 | A failing image is rejected with a clear reason, not silently altered |
| R6 | The stored image contains only the detected colours, so 3D export stays valid |
| R7 | Sizing, pricing, the quota and STL export behave identically on both paths |
| R8 | The order records which path produced it |
| R9 | Admins can tune the strictness of the check, and disable the path entirely |
| R10 | The UI suggests a concrete way to produce a suitable image (AI model + copyable prompt) |

### 4.8 Admin panel

| ID | Requirement |
|---|---|
| A1 | Order list with thumbnail, user, size, cost and status |
| A2 | Status changes, individually and in bulk |
| A3 | Record an admin note and the final cost |
| A4 | Reviewer and review time recorded automatically |
| A5 | Colour profile management with a colour picker |
| A6 | Management of the size range and the price per cm² |
| A7 | User management, including promotion to admin |
| A8 | Configuration of the render defaults |
| A9 | Configuration of the 3D export parameters, and STL download |
| A10 | Configuration of ready-image acceptance rules and the AI helper prompt |

---

## 5. Non-functional requirements

| Area | Requirement |
|---|---|
| Language | The entire UI in Persian, `dir="rtl"`, Jalali dates, Persian digits |
| Performance | A 1400×1700 image processed in under 10 seconds |
| Mobile | Responsive layout down to 320 px wide |
| Security | CSRF on every request, sign-in rate limiting, private images |
| Maintenance | One-command install, one-command backup, one-command restore |
| Reliability | systemd service with `Restart=always` |

---

## 6. Out of scope (for now)

- Online payment — the price is only quoted
- SMS/email notifications
- Multi-language support
- Automatic password recovery (currently handled by an admin)
- Bulk STL download across several orders

---

## 7. Acceptance criteria

The system is complete when:

1. A guest can render and download an image without signing in. ✅
2. A user who signs in via the modal can order that same image with no page reload. ✅
3. A fourth unreviewed order is rejected. ✅
4. The frame height is derived from the image ratio and browser tampering has no effect. ✅
5. An admin can change the status and the final price. ✅
6. `install.sh` brings the app up on a fresh server. ✅
7. `backup.sh` + `restore.sh` move the state across intact. ✅
8. Changing the defaults in the admin panel is visible on the landing page immediately. ✅
9. The generated STL file is a closed, printable solid. ✅
