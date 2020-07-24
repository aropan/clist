"""
WSGI config for pyclist project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.8/howto/deployment/wsgi/
"""

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pyclist.settings")  # noqa

from git import Repo
from django.core.wsgi import get_wsgi_application
from django.core.management import call_command
from django import setup
from django.conf import settings

if not settings.DEBUG:
    setup()
    call_command('collectstatic', verbosity=1, interactive=False)
    repo = Repo(os.path.join(os.path.dirname(__file__), '..'))
    print('Submodule update:', repo.git.submodule('update', '--init'))

application = get_wsgi_application()
