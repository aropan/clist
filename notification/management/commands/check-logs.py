#!/usr/bin/env python
# -*- coding: utf-8 -*-

import glob
import hashlib
import logging
import os
import re

import coloredlogs
import yaml
from django.core.management.base import BaseCommand

from clist.templatetags.extras import md_escape
from tg.bot import Bot

logger = logging.getLogger('notify.error')
coloredlogs.install(logger=logger)


class Command(BaseCommand):
    help = 'Notify errors'

    def _check(self, filepath, regex, cache, key, href=None, flags=re.MULTILINE | re.IGNORECASE):
        if not os.path.exists(filepath):
            return
        logger.info(f'log file is {filepath}')
        with open(filepath, 'r') as fo:
            errors = []
            for m in re.finditer(
                regex,
                fo.read(),
                flags,
            ):
                error = m.group(0)
                if re.search('contest = ', error):
                    continue
                logger.error(error)
                errors.append(error)
            if errors:
                errors = '\n'.join(errors)
                msg = f'{md_escape(href or key)}\n```\n{errors}\n```'

                h = hashlib.md5(msg.encode('utf8')).hexdigest()
                if cache.get(key) != h:
                    cache[key] = h
                    self._bot.admin_message(msg)
            else:
                cache.pop(key, None)
        logger.info('done')

    def __init__(self):
        self._bot = Bot()

    def handle(self, *args, **options):
        logger.info('start')
        cache_filepath = os.path.join(os.path.dirname(__file__), 'cache.yaml')
        if os.path.exists(cache_filepath):
            with open(cache_filepath, 'r') as fo:
                cache = yaml.safe_load(fo)
        else:
            cache = {}

        self._check(
            './legacy/logs/update/index.html',
            regex=r'php[\w\s]*:.*$',
            cache=cache,
            key='update-file-error-hash',
            href='https://legacy.clist.by/logs/update/',
        )

        command_cache = cache.setdefault('command', {})
        files = list(glob.glob('./logs/command/**/*.log', recursive=True))
        for log_file in files:
            if not os.path.exists(log_file):
                continue
            key = os.path.basename(log_file)
            regex = r'^[^-\{\+\!\n]*\b(error\b|exception\b[^\(]).*$'
            self._check(log_file, regex, command_cache, key)

        cache = yaml.dump(cache, default_flow_style=False)
        with open(cache_filepath, 'w') as fo:
            fo.write(cache)
        logger.info('end')
