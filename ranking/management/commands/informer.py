#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import time
import json
import subprocess

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
        parser.add_argument('--numbered', help='Regex numbering query', default=None)
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

        problems_info = standings.setdefault('__problems_info', {})

        parser_command = ParserCommand()

        iteration = 1 if args.dump else 0
        while True:
            subprocess.call('clear', shell=True)

            contest = Contest.objects.get(pk=args.cid)
            parser_command.parse_statistic([contest], with_check=False, calculate_time=True)
            statistics = Statistics.objects.filter(contest=contest)

            updated = False
            has_hidden = False
            numbered = 0
            for stat in sorted(statistics, key=lambda s: s.place_as_int):
                filtered = False
                if args.query is not None and re.search(args.query, stat.account.key, re.I):
                    filtered = True

                message_id = None
                key = str(stat.account.id)
                if key in standings:
                    problems = standings[key]['problems']
                    message_id = standings[key].get('messageId')
                    p = []
                    has_update = False
                    has_first_ac = False
                    for k, v in stat.addition.get('problems', {}).items():
                        p_info = problems_info.setdefault(k, {})
                        p_result = problems.get(k, {}).get('result')
                        result = v['result']
                        is_hidden = result.startswith('?')
                        try:
                            is_accepted = result.startswith('+')
                            is_accepted = is_accepted or float(result) > 0
                        except Exception:
                            pass
                        if p_result != result or is_hidden:
                            m = '%s%s %s' % (k, ('. ' + v['name']) if 'name' in v else '', result)

                            if p_result != result:
                                m = '*%s*' % m
                                has_update = True
                                if iteration and is_accepted and not p_info.get('accepted'):
                                    m += ' FIRST ACCEPTED'
                                    has_first_ac = True
                                if is_accepted and args.top and stat.place_as_int <= args.top:
                                    filtered = True
                            p.append(m)
                        if result.startswith('+'):
                            p_info['accepted'] = True
                        has_hidden = has_hidden or is_hidden

                    if args.numbered is not None and re.search(args.numbered, stat.account.key, re.I):
                        numbered += 1
                        place = '%s (%s)' % (stat.place, numbered)
                    else:
                        place = stat.place

                    msg = '%s. _%s_ %s' % (place, stat.account.key, ', '.join(p))
                    if standings[key]['solving'] != stat.solving:
                        msg += ' = %d' % stat.solving

                    if has_update or has_first_ac:
                        updated = True

                    if filtered:
                        print(msg)

                    if filtered and has_update or has_first_ac:
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

            if iteration:
                is_over = contest.end_time < now()
                if is_over and not has_hidden:
                    break
                time.sleep(args.delay * (60 if is_over else 1))

            iteration += 1
