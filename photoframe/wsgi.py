"""WSGI config for the Photo Frame 2D project."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "photoframe.settings")

application = get_wsgi_application()
