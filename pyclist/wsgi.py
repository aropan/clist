"""
WSGI config for pyclist project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.8/howto/deployment/wsgi/
"""

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pyclist.settings")  # noqa

from django.core.wsgi import get_wsgi_application
from django.core.management import call_command
from django import setup
from django.conf import settings

if not settings.DEBUG:
    setup()
    call_command('collectstatic', verbosity=1, interactive=False)

application = get_wsgi_application()
