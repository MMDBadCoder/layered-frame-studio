#!/usr/bin/env python3
"""
Build a Photo Frame 2D state archive.

Everything that is NOT in a fresh clone of the repo goes in here:

    db.sqlite3   the database (users, orders, profiles, prices, settings)
    media/       order images (result + original)
    uploads/     in-progress renders belonging to live sessions
    .env         the secret key, so restored sessions keep working

Called by scripts/backup.sh. Uses only the standard library, so it still works
when the virtualenv is missing or broken.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_database(db_path: Path, target: Path) -> None:
    """
    Copy the database using SQLite's online backup API.

    A plain file copy of a live database can capture a torn write; this cannot,
    so backups are safe to take while the service is serving traffic.
    """
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()


def database_summary(db_path: Path) -> dict:
    """Row counts, purely informational — never fail the backup over these."""
    counts = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            for label, table in (
                ("users", "accounts_user"),
                ("orders", "posterizer_order"),
                ("color_profiles", "posterizer_colorprofile"),
            ):
                try:
                    counts[label] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                except sqlite3.Error:
                    counts[label] = None
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    return counts


def add_tree(archive: zipfile.ZipFile, root: Path, arc_root: str, entries: list) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        arcname = f"{arc_root}/{path.relative_to(root).as_posix()}"
        archive.write(path, arcname)
        entries.append({"path": arcname, "size": path.stat().st_size})


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Photo Frame 2D state archive.")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--output", required=True, help="destination .zip path")
    parser.add_argument("--no-uploads", action="store_true", help="skip the scratch uploads/ dir")
    parser.add_argument("--no-env", action="store_true", help="skip .env (excludes the secret key)")
    args = parser.parse_args()

    project = Path(args.project_dir).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    db_path = project / "db.sqlite3"
    entries: list = []

    manifest = {
        "format_version": FORMAT_VERSION,
        "application": "photo-frame-2d",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hostname": os.uname().nodename,
        "source_project_dir": str(project),
        "includes_uploads": not args.no_uploads,
        "includes_env": not args.no_env,
    }

    with tempfile.TemporaryDirectory() as tmp:
        staged_db = Path(tmp) / "db.sqlite3"

        # Zip with deflate; images are already PNG so the win comes from the DB.
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            if db_path.exists():
                snapshot_database(db_path, staged_db)
                archive.write(staged_db, "db.sqlite3")
                entries.append({"path": "db.sqlite3", "size": staged_db.stat().st_size})
                manifest["database_sha256"] = sha256(staged_db)
                manifest["counts"] = database_summary(staged_db)
            else:
                manifest["counts"] = {}
                print("warning: db.sqlite3 not found — archive will contain no database",
                      file=sys.stderr)

            add_tree(archive, project / "media", "media", entries)
            if not args.no_uploads:
                add_tree(archive, project / "uploads", "uploads", entries)

            env_file = project / ".env"
            if env_file.exists() and not args.no_env:
                archive.write(env_file, ".env")
                entries.append({"path": ".env", "size": env_file.stat().st_size})

            manifest["files"] = entries
            manifest["file_count"] = len(entries)
            manifest["total_uncompressed_bytes"] = sum(e["size"] for e in entries)
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, ensure_ascii=False))

    size_mb = output.stat().st_size / 1e6
    counts = manifest.get("counts") or {}
    print(json.dumps({
        "output": str(output),
        "size_mb": round(size_mb, 2),
        "files": len(entries),
        "counts": counts,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
