# Operations guide — Photo Frame 2D

A practical guide to installing, backing up, restoring and troubleshooting.

---

## 1. Installing on a fresh Ubuntu server

```bash
git clone <repo-url> photo-frame-2d
cd photo-frame-2d
sudo ./scripts/install.sh
sudo ./scripts/create-admin.sh
```

`install.sh` does the following:

1. Installs the required system packages (`python3-venv`, `python3-pip`, `curl`)
2. Creates `.venv` and installs `requirements.txt`
3. Creates `.env` with a **random secret key** (if it does not exist yet)
4. Runs migrations and `collectstatic`
5. Fixes ownership of the state files
6. Writes and starts the systemd service
7. Opens the port in ufw
8. Health-checks the result with a real HTTP request

### Options
```bash
sudo ./scripts/install.sh --port 9000      # different port
sudo ./scripts/install.sh --host 127.0.0.1 # local only (behind nginx)
sudo ./scripts/install.sh --user www-data  # user the service runs as
sudo ./scripts/install.sh --debug          # development mode (never on a public server)
sudo ./scripts/install.sh --skip-apt       # skip apt
```

### Idempotency
Re-running is safe: the secret key, the database and the images are left
untouched, and only the dependencies, migrations, static files and the service
unit are refreshed. Use this same command to **update after a `git pull`**.

---

## 2. Day-to-day service operations

```bash
systemctl status photo-frame-2d          # status
systemctl restart photo-frame-2d         # restart
journalctl -u photo-frame-2d -f          # live logs
journalctl -u photo-frame-2d -n 100      # last 100 lines
```

---

## 3. Backups

```bash
./scripts/backup.sh                       # backups/photo-frame-2d-backup-<date>.zip
./scripts/backup.sh --output /mnt/nas/pf.zip
./scripts/backup.sh --keep 7              # keep only the 7 newest
./scripts/backup.sh --no-uploads          # skip temporary files (smaller)
./scripts/backup.sh --no-env              # skip the secret key
```

### What is inside a backup?
| Path | Contents |
|---|---|
| `db.sqlite3` | Users, orders, profiles, prices, settings |
| `media/` | Order images |
| `uploads/` | Temporary renders of live sessions |
| `.env` | Secret key and configuration |
| `manifest.json` | Date, record counts, database checksum |

The database is copied through the **SQLite online backup API**, so taking a
backup while the service is running is safe and never yields a half-written
file.

> ⚠️ A backup archive contains users' personal data and the secret key.
> Encrypt it or keep it somewhere safe.

### Automatic backups (cron)
```bash
sudo crontab -e
# every night at 03:00, keeping the 14 newest
0 3 * * * /home/root/projects/Photo-Frame-2D/scripts/backup.sh --keep 14 --quiet
```

---

## 4. Restoring

```bash
./scripts/restore.sh --inspect backups/photo-frame-2d-backup-....zip   # show only
sudo ./scripts/restore.sh backups/photo-frame-2d-backup-....zip        # restore
```

Automatic steps:
1. Validate the archive and check the database's integrity
2. **Take a safety snapshot of the current state** (`backups/pre-restore-<date>.zip`)
3. Stop the service
4. Replace the database, `media/`, `uploads/` and `.env`
5. Fix ownership for the service user
6. Run migrations (in case the backup is older)
7. Start the service and health-check it

### Options
```bash
--skip-env     # keep the current secret key
--yes          # no confirmation prompt (for scripting)
--no-safety    # no safety snapshot (not recommended)
```

### Moving to a new server
```bash
# old server
./scripts/backup.sh --output /tmp/move.zip
scp /tmp/move.zip newserver:/tmp/

# new server
git clone <repo-url> photo-frame-2d && cd photo-frame-2d
sudo ./scripts/install.sh
sudo ./scripts/restore.sh /tmp/move.zip --yes
```

---

## 5. User management

```bash
sudo ./scripts/create-admin.sh                      # interactive
sudo ./scripts/create-admin.sh \
    --phone 09121234567 --email a@b.com \
    --name "Admin Name" --generate-password --noinput
```

If the mobile number already exists, that account is promoted and its orders
are left untouched.

### Changing a password
```bash
.venv/bin/python manage.py changepassword 09121234567
```

---

## 6. Uninstalling

```bash
sudo ./scripts/uninstall.sh                 # service only; data stays
sudo ./scripts/uninstall.sh --purge-venv    # + remove .venv
sudo ./scripts/uninstall.sh --remove-ufw    # + remove the firewall rule
sudo ./scripts/uninstall.sh --purge-data    # + remove all data (asks for confirmation)
```

`--purge-data` automatically takes a backup before deleting anything.

---

## 7. Periodic maintenance

```bash
.venv/bin/python manage.py cleanup_uploads --days 7 --dry-run
.venv/bin/python manage.py cleanup_uploads --days 7
```

The `uploads/` directory holds temporary session renders and grows over time.
Order images live in `media/` and are **never** deleted by this command.

Suggested cron entry:
```
30 3 * * 0 /home/root/projects/Photo-Frame-2D/.venv/bin/python \
           /home/root/projects/Photo-Frame-2D/manage.py cleanup_uploads --days 7
```

---

## 7.5 3D export

STL generation happens on the server, on demand; nothing is stored.

- For an image at resolution 400, the file is roughly **20–25 MB** and takes
  about **1 second** to build.
- If the files are larger than you need, lower the "maximum 3D model
  resolution"; size scales roughly with the square of that number.
- Total model height = layer count × "layer height". With 5 layers at 2 mm, the
  tallest point is 10 mm.

---

## 7.6 Tuning ready-image acceptance

Admin panel → shop settings → "پذیرش تصاویر آماده".

| Setting | Effect |
|---|---|
| Accept ready images | Turns the whole second path off; the mode switch disappears |
| Maximum colours | Images resolving to more layers than this are rejected |
| Minimum coverage | Lower it to accept softer images; raise it to be stricter about gradients |
| Minimum layer share | How much of the image a colour must cover to count as a layer |

If genuine artwork is being rejected, lower the minimum coverage a little
(98% is still safely clear of photographs). If noisy images are getting
through, raise the minimum layer share.

The AI prompt customers copy lives in the same settings page, under
"راهنمای ساخت با هوش مصنوعی". Editing it takes effect immediately; no deploy
is needed.

---

## 7.7 Replacing the logo

```bash
.venv/bin/python scripts/make_logo.py path/to/new-logo.png
.venv/bin/python manage.py collectstatic --noinput
systemctl restart photo-frame-2d
```

The script writes every brand asset from one source image: the inline SVG the
header uses, an SVG favicon, a 512px transparent master and the 16/32/180px
icon set. It handles what logo files usually arrive as — a JPEG with a white
background, wide margins and compression ringing:

- The alpha is *unmixed* rather than colour-keyed, so edges stay smooth and the
  ringing fades out instead of leaving a halo.
- If the mark is made of axis-aligned rectangles it is re-emitted as exact
  vector geometry, which is sharper than resampling the original could be.
  Marks with curves keep the existing SVG and get raster assets only.
- Colours are snapped to the site accent, so the header matches its own token.

Pass `--accent` or `--background` if either differs from the defaults
(`#6c8cff` on `#ffffff`).

---

## 8. Troubleshooting

| Symptom | Check |
|---|---|
| Service will not start | `journalctl -u photo-frame-2d -n 50` |
| Port already in use | `ss -ltnp \| grep 8080` |
| Page has no styling | `collectstatic` did not run → `sudo ./scripts/install.sh` |
| CSS/JS edits are not visible | With `DEBUG=0`, WhiteNoise serves `staticfiles/`, not `static/`. Run `manage.py collectstatic --noinput` and restart, or just `sudo ./scripts/install.sh` |
| 403 errors on requests | CSRF problem → clear cookies and reload the page |
| "تصویری یافت نشد" ("image not found") | The session's temporary file was cleaned up → upload the image again |
| Wrong price | Admin panel → site settings → price per square centimetre |
| A user cannot place an order | Their quota of 3 unreviewed orders is full |
| Superpixels disabled | Requires `opencv-contrib-python-headless` |
| STL file is far too large | Lower the "maximum 3D model resolution" in the site settings |
| The 3D model is upside down (light areas raised) | Site settings → tick "تیره‌ترین لایه بلندترین باشد" |
| The studio opens with the wrong settings | Site settings → render defaults |

### Quick rollback after a mistake
```bash
ls -1t backups/pre-restore-*.zip | head -1     # the newest safety snapshot
sudo ./scripts/restore.sh backups/pre-restore-....zip
```

---

## 9. Hardening for production

1. **HTTPS**: behind nginx with Let's Encrypt, plus `install.sh --host 127.0.0.1`
2. **Firewall**:
```bash
ufw allow OpenSSH      # this one first
ufw enable
```
3. **`ALLOWED_HOSTS`**: restrict it to the real domain in `photoframe/settings.py`
4. **A separate user**: `sudo ./scripts/install.sh --user www-data`
5. **Off-server backups**: copy the zip to cloud storage or a NAS
