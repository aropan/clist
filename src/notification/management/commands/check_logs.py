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
            logger.warning(f'skip {filepath}')
            return
        logger.info(f'check {filepath}')
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
                logger.warning(error)
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

    def __init__(self):
        self._bot = Bot()

    def handle(self, *args, **options):
        logger.info('start')
        cache_filepath = os.path.join('./logs/cache.yaml')
        if os.path.exists(cache_filepath):
            with open(cache_filepath, 'r') as fo:
                cache = yaml.safe_load(fo)
        else:
            cache = {}
        check_logs_cache = cache.setdefault('check_logs', {})

        self._check(
            './logs/legacy/update/index.html',
            regex=r'php[\w\s]*:.*$',
            cache=check_logs_cache,
            key='legacy/update/index.html',
            href='https://legacy.clist.by/logs/update/',
        )

        files = []
        files.extend(glob.glob('./logs/*/**/*.log', recursive=True))
        files.extend(glob.glob('./logs/*/**/*.txt', recursive=True))
        for log_file in files:
            if log_file.endswith('check_logs.log'):
                continue
            if '/legacy/removed/' in log_file:
                continue
            key = os.path.relpath(log_file, 'logs')
            regex = r'^[^-\{\+\!\n]*\b(error\b|exception\b[^\(]).*$'
            self._check(log_file, regex, check_logs_cache, key)

        cache = yaml.dump(cache, default_flow_style=False)
        with open(cache_filepath, 'w') as fo:
            fo.write(cache)
        logger.info('end')
