"""ASGI config for the Photo Frame 2D project."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "photoframe.settings")

application = get_asgi_application()
