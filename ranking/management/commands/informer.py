#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import time
import json

from attrdict import AttrDict

from django.core.management.base import BaseCommand
from django.utils.timezone import now

from clist.models import Contest
from ranking.models import Statistics

from tg.bot import Bot

from .parse_statistic import Command as ParserCommand


class Command(BaseCommand):
    help = 'Informer'

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)

    def add_arguments(self, parser):
        parser.add_argument('--cid', type=int, help='Contest id', required=True)
        parser.add_argument('--tid', type=int, help='Telegram id for info', required=True)
        parser.add_argument('--delay', type=int, help='Delay between query in seconds', default=30)
        parser.add_argument('--query', help='Regex search query', default=None)
        parser.add_argument('--top', type=int, help='Number top ignore query', default=None)
        parser.add_argument('--dryrun', action='store_true', help='Do not send to bot message', default=False)
        parser.add_argument('--dump', help='Dump and restore log file', default=None)

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        bot = Bot()

        if args.dump is not None and os.path.exists(args.dump):
            with open(args.dump, 'r') as fo:
                standings = json.load(fo)
        else:
            standings = {}

        contest = Contest.objects.get(pk=args.cid)

        parser_command = ParserCommand()

        it = 0
        while True:
            parser_command.parse_statistic([contest], with_check=False)
            statistics = Statistics.objects.filter(contest=contest)
            updated = False
            for stat in statistics:
                if args.query is not None and not re.search(args.query, stat.account.key, re.I):
                    if args.top is None or int(re.search('^[0-9]+', stat.place).group(0)) > args.top:
                        continue
                message_id = None
                key = stat.account.id
                if key in standings:
                    problems = standings[key]['problems']
                    message_id = standings[key].get('messageId')
                    p = []
                    u = False
                    for k, v in list(stat.addition.get('problems', {}).items()):
                        r = problems.get(k, {}).get('result')
                        if r != v['result'] or v['result'].startswith('?'):
                            m = '%s%s %s' % (k, ('. ' + v['name']) if 'name' in v else '', v['result'])
                            if r != v['result']:
                                m = '*%s*' % m
                                u = True
                            p.append(m)
                    msg = '%s. _%s_ %s' % (stat.place, stat.account.key, ', '.join(p))
                    if standings[key]['solving'] != stat.solving:
                        msg += ' = %d' % stat.solving
                    print(msg)
                    if u:
                        updated = True
                        if not args.dryrun:
                            if message_id:
                                bot.delete_message(chat_id=args.tid, message_id=message_id)
                            message = bot.send_message(msg=msg, chat_id=args.tid)
                            message_id = message.message_id
                standings[key] = {
                    'solving': stat.solving,
                    'problems': stat.addition.get('problems', {}),
                    'messageId': message_id,
                }
            if args.dump is not None and (updated or not os.path.exists(args.dump)):
                standings_dump = json.dumps(standings, indent=2)
                with open(args.dump, 'w') as fo:
                    fo.write(standings_dump)
            if it > 0:
                if contest.end_time < now():
                    break
                time.sleep(args.delay)
            it += 1
