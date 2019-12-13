#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import logging
import coloredlogs
import yaml
import hashlib


from tg.bot import Bot
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Notify errors'

    def handle(self, *args, **options):
        logger = logging.getLogger('notify.error')
        coloredlogs.install(logger=logger)

        bot = Bot()

        cache_filepath = os.path.join(os.path.dirname(__file__), 'cache.yaml')
        if os.path.exists(cache_filepath):
            with open(cache_filepath, 'r') as fo:
                cache = yaml.load(fo)
        else:
            cache = {}

        filepath = './legacy/logs/update/index.html'
        key = 'update-file-error-hash'
        if os.path.exists(filepath):
            logger.info(f'log file is {filepath}')
            with open(filepath) as fo:
                errors = []
                for m in re.finditer(
                    'php.*:.*$',
                    fo.read(),
                    re.MULTILINE | re.IGNORECASE
                ):
                    error = m.group(0)
                    logger.error(error)
                    errors.append(error)
                if errors:
                    errors = '\n'.join(errors)
                    msg = f'https://legacy.clist.by/logs/update/: ```\n{errors}\n```'

                    h = hashlib.md5(msg.encode('utf8')).hexdigest()
                    if cache.get(key) != h:
                        cache[key] = h
                        bot.admin_message(msg)
                else:
                    cache.pop(key, None)

        cache = yaml.dump(cache, default_flow_style=False)
        with open(cache_filepath, 'w') as fo:
            fo.write(cache)
