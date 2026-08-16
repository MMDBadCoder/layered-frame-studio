"""
Delete stale scratch files from uploads/.

The studio keeps each visitor's uploaded image and its latest render on disk so
that "Apply changes" and order submission do not need a re-upload. Those files
are throwaway — order images are copied into media/ — so anything older than a
few days can go.

    python manage.py cleanup_uploads --days 7
"""

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Delete stale temporary files from the uploads directory"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=7, help="delete files older than this many days"
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="report only, delete nothing"
        )

    def handle(self, *args, **options):
        upload_dir = Path(settings.BASE_DIR) / "uploads"
        if not upload_dir.exists():
            self.stdout.write("The uploads directory does not exist.")
            return

        cutoff = time.time() - options["days"] * 86400
        removed = freed = 0

        for path in upload_dir.iterdir():
            if not path.is_file() or path.stat().st_mtime >= cutoff:
                continue

            size = path.stat().st_size
            if not options["dry_run"]:
                path.unlink()
            removed += 1
            freed += size

        verb = "removable" if options["dry_run"] else "deleted"
        self.stdout.write(
            self.style.SUCCESS(f"{removed} files {verb} ({freed / 1e6:.1f} MB)")
        )
