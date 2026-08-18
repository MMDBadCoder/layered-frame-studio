# Layered Frame Studio — Photo Frame 3D

A Persian, right-to-left web studio that turns a photograph into a layered
poster image using an admin-defined colour palette, then lets the customer order
a physical frame at a chosen size with an estimated price.

> **Language policy:** the application UI is entirely Persian and RTL (Jalali
> dates, Persian digits). All developer-facing material — this README, the
> `docs/` folder, the changelog and the maintenance scripts — is English.

---

## What it does

A visitor uploads a photo without signing in, picks one of the colour profiles
defined by an admin, tunes the processing parameters and sees the result live.
They then choose a frame size, see an approximate price, and submit the order
for admin review.

1. **Render** — upload a photo, pick a colour profile, tune the pipeline, see the result. No sign-in required.
2. **Size & price** — choose a frame width; the height follows the photo's aspect ratio automatically. An approximate price is shown live.
3. **Order** — sign in (in a modal, so the render is never lost), confirm, submit.
4. **Review** — admins triage orders in the Django admin panel and set the final price.
5. **Or bring your own** — already have a layered image? Upload it, we verify it is built from solid colours, and it becomes an order directly.
6. **Produce** — admins export any order as a printable **3D STL plate**, one terrace per colour.

Admins also control what the studio looks like when it first opens: the default
colour profile and every processing parameter, with no code changes.

---

## Quick start

On an Ubuntu server, a single command:

```bash
sudo ./scripts/install.sh
```

That one idempotent command installs system packages, builds the virtualenv,
applies migrations, collects static files, writes a systemd unit, opens the
firewall port and health-checks the result. Run it as often as you like.

Then create an admin:

```bash
sudo ./scripts/create-admin.sh
```

- Application: `http://<server>:8080/`
- Admin panel: `http://<server>:8080/admin/`

### Local development

```bash
./run.sh                       # http://0.0.0.0:8080 with autoreload
.venv/bin/python manage.py test
```

---

## Maintenance scripts

Every script can be run from any working directory — each one locates the
project root itself.

| Script | Purpose |
|---|---|
| `scripts/install.sh` | Full install/update plus the systemd service. **Idempotent** |
| `scripts/uninstall.sh` | Remove the service. Data is kept by default |
| `scripts/create-admin.sh` | Create a superuser, or promote an existing user |
| `scripts/backup.sh` | Pack the entire runtime state into one zip file |
| `scripts/restore.sh` | Restore the runtime state from a backup file |
| `scripts/make_logo.py` | Rebuild the brand mark and favicons from one image |

```bash
sudo ./scripts/install.sh --port 9000        # install on a different port
./scripts/backup.sh --keep 7                 # back up, keep the 7 newest
./scripts/restore.sh --inspect backup.zip    # show the contents only
sudo ./scripts/restore.sh backup.zip         # full restore
sudo ./scripts/uninstall.sh                  # remove service, keep data
```

Full details in [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

---

## What counts as state

Anything that does not exist in a fresh clone and has to survive:

| Path | Contents |
|---|---|
| `db.sqlite3` | Users, orders, colour profiles, prices, settings |
| `media/` | Order images (result + original) |
| `uploads/` | Temporary files belonging to live sessions |
| `.env` | Secret key and per-server configuration |

`backup.sh` puts all four into a single zip. None of them are in git.

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/PRD.md`](docs/PRD.md) | Product requirements: why, for whom, under which rules |
| [`docs/FEATURES.md`](docs/FEATURES.md) | Every feature and its exact behaviour |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Code layout, data model, API, technical decisions |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | Install, backup, restore, troubleshooting |
| [`CHANGELOG.md`](CHANGELOG.md) | Release history — current release **v1.0.0** |

---

## 3D export

From any order's page in the admin panel, use the **دانلود فایل STL**
("Download STL file") button.

Every palette colour becomes a terrace at a consecutive multiple of the base
height `x`, with the **darkest colour tallest** — dark areas are the deep ones
on a layered frame. The value of `x`, the direction and the model resolution
are all editable under **Site settings** in the admin panel. The plate's footprint matches the ordered frame size exactly.

The output is a closed, manifold solid with outward-facing normals — ready to
slice in any slicer. The algorithm is described in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Stack

- **Django 6** + **SQLite** — deliberately simple, so maintenance and backups stay easy
- **gunicorn** + **WhiteNoise** — no nginx required to get started
- **OpenCV / NumPy / scikit-image / Pillow** — the image processing engine (`main.py`)
- **No JavaScript framework** — three plain files: `auth.js`, `app.js`, `style.css`
- **Django admin panel** — Persian and RTL out of the box

---

## Security notes

- `PHOTO_FRAME_DEBUG=0` is mandatory on a public server (and is what `install.sh` sets).
- The app serves plain HTTP; for real deployments put it behind nginx with HTTPS.
- Order images are private — only the order's owner and admins can fetch them.
- Backup archives contain `.env` and users' personal data — store them securely.

---

## Standalone CLI

`main.py` works independently of the web app:

```bash
.venv/bin/python main.py input.jpg output.png --num-levels 4 \
    --preprocess bilateral --postprocess connected_components
```
