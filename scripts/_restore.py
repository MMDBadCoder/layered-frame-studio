#!/usr/bin/env python3
"""
Restore a Photo Frame 3D state archive produced by _backup.py.

Replaces the database, order images and (optionally) the secret key with the
contents of the archive. Called by scripts/restore.sh, which stops the service
first and takes a safety snapshot of the current state.

Standard library only, so it works before the virtualenv exists.
"""

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

MANIFEST_NAME = "manifest.json"
SUPPORTED_FORMATS = {1}

# Archives written before the product was renamed from 2D to 3D declare the old
# application name. They restore perfectly well, so both are accepted.
ACCEPTED_APPLICATIONS = {"photo-frame-3d", "photo-frame-2d"}


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def read_manifest(archive: zipfile.ZipFile) -> dict:
    try:
        raw = archive.read(MANIFEST_NAME)
    except KeyError:
        fail("this is not a valid Photo Frame 3D backup (no manifest.json).")

    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError:
        fail("manifest.json is corrupt.")

    if manifest.get("application") not in ACCEPTED_APPLICATIONS:
        fail("this backup belongs to a different application.")

    version = manifest.get("format_version")
    if version not in SUPPORTED_FORMATS:
        fail(f"backup format version {version} is not supported.")

    return manifest


def safe_members(archive: zipfile.ZipFile) -> list:
    """Reject absolute paths and ../ escapes before extracting anything."""
    members = []
    for name in archive.namelist():
        if name.startswith("/") or ".." in Path(name).parts:
            fail(f"unsafe path inside the backup: {name}")
        members.append(name)
    return members


def verify_database(path: Path) -> None:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            fail(f"the database inside the backup is not intact: {result}")
    except sqlite3.DatabaseError as exc:
        fail(f"could not read the database inside the backup: {exc}")
    finally:
        conn.close()


def replace_tree(staged: Path, target: Path) -> None:
    if not staged.exists():
        return
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(staged, target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a Photo Frame 3D state archive.")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--skip-env", action="store_true", help="keep the current .env")
    parser.add_argument("--inspect", action="store_true", help="print the manifest and exit")
    args = parser.parse_args()

    project = Path(args.project_dir).resolve()
    archive_path = Path(args.archive).resolve()

    if not archive_path.exists():
        fail(f"backup file not found: {archive_path}")
    if not zipfile.is_zipfile(archive_path):
        fail("the given file is not a valid zip archive.")

    with zipfile.ZipFile(archive_path) as archive:
        manifest = read_manifest(archive)

        if args.inspect:
            print(json.dumps(manifest, indent=2, ensure_ascii=False))
            return 0

        members = safe_members(archive)

        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp)
            archive.extractall(staging, members=members)

            staged_db = staging / "db.sqlite3"
            if staged_db.exists():
                verify_database(staged_db)
                shutil.copy2(staged_db, project / "db.sqlite3")

            replace_tree(staging / "media", project / "media")
            if (staging / "uploads").exists():
                replace_tree(staging / "uploads", project / "uploads")

            staged_env = staging / ".env"
            if staged_env.exists() and not args.skip_env:
                shutil.copy2(staged_env, project / ".env")
                (project / ".env").chmod(0o600)

    (project / "media").mkdir(exist_ok=True)
    (project / "uploads").mkdir(exist_ok=True)

    print(json.dumps({
        "restored_from": str(archive_path),
        "created_at": manifest.get("created_at"),
        "counts": manifest.get("counts", {}),
        "env_restored": (not args.skip_env) and manifest.get("includes_env", False),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
