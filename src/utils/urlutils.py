#!/usr/bin/env python3


from urllib.parse import urljoin

from django.conf import settings


def absolute_url(url):
    return urljoin(settings.HTTPS_HOST_URL_, url)
