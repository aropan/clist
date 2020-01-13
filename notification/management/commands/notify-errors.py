#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import glob
import re
import logging
import coloredlogs
import yaml
import hashlib


from tg.bot import Bot
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Notify errors'

    def _check(self, filepath, regex, cache, key, href=None, flags=None):
        self._logger.info(f'log file is {filepath}')
        with open(filepath, 'r') as fo:
            errors = []
            for m in re.finditer(
                regex,
                fo.read(),
                flags,
            ):
                error = m.group(0)
                self._logger.error(error)
                errors.append(error)
            if errors:
                errors = '\n'.join(errors)
                msg = f'{href or key}\n```\n{errors}\n```'

                h = hashlib.md5(msg.encode('utf8')).hexdigest()
                if cache.get(key) != h:
                    cache[key] = h
                    self._bot.admin_message(msg)
            else:
                cache.pop(key, None)

    def __init__(self):
        self._logger = logging.getLogger('notify.error')
        coloredlogs.install(logger=self._logger)

        self._bot = Bot()

    def handle(self, *args, **options):

        cache_filepath = os.path.join(os.path.dirname(__file__), 'cache.yaml')
        if os.path.exists(cache_filepath):
            with open(cache_filepath, 'r') as fo:
                cache = yaml.load(fo)
        else:
            cache = {}

        filepath = './legacy/logs/update/index.html'
        key = 'update-file-error-hash'
        if os.path.exists(filepath):
            self._check(
                filepath,
                regex='php.*:.*$',
                cache=cache,
                key=key,
                href='https://legacy.clist.by/logs/update/',
                flags=re.MULTILINE | re.IGNORECASE,
            )

        command_cache = cache.setdefault('command', {})
        for log_file in glob.glob('/home/aropan/dev/clist/logs/command/**/*.log', recursive=True):
            key = os.path.basename(log_file)
            self._check(log_file, '^.*ERROR.*$', command_cache, key, flags=re.MULTILINE)

        cache = yaml.dump(cache, default_flow_style=False)
        with open(cache_filepath, 'w') as fo:
            fo.write(cache)
