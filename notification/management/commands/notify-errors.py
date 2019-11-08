#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import logging
import coloredlogs

from tg.bot import Bot
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Notify errors'

    def handle(self, *args, **options):
        logger = logging.getLogger('notify.error')
        coloredlogs.install(logger=logger)

        bot = Bot()

        filepath = './legacy/logs/update/index.txt'
        if os.path.exists(filepath):
            with open(filepath, 'r') as fo:
                errors = []
                for m in re.finditer('php.* in [^ ]* on line [0-9]+$', fo.read(), re.MULTILINE | re.IGNORECASE):
                    errors.append(m.group(0))
                if errors:
                    errors = '\n'.join(errors)
                    msg = f'https://legacy.clist.by/logs/update/: ```\n{errors}\n```'
                    bot.admin_message(msg)
