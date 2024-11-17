#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
# import os
# import re
# import subprocess
import time

# import coloredlogs
# import flag
import humanize
# from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
# from django.db.models import Q
# from django.urls import reverse
from django.utils import timezone

from ranking.models import ParseStatistics
# from clist.models import Contest
# from clist.templatetags.extras import (as_number, get_problem_name, get_problem_short, has_season, md_escape, md_url,
#                                        scoreformat, solution_time_compare)
# from notification.models import Subscription
# from ranking.models import Statistics
# from tg.bot import MAX_MESSAGE_LENGTH, Bot, telegram
# from tg.models import Chat
# from true_coders.models import CoderList
from utils.attrdict import AttrDict

# from datetime import timedelta
# from pprint import pprint  # noqa

# from rich.console import Console
# from rich.markdown import Markdown
# from rich.table import Table

# from utils.strings import trim_on_newline


class Command(BaseCommand):
    help = 'Parse live statistics'

    def add_arguments(self, parser):
        parser.add_argument('--dryrun', action='store_true', default=False)
        self.logger = logging.getLogger('ranking.parse.live_statistics')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)
        logging.disable(logging.DEBUG)

        while True:
            now = timezone.now()
            parse_statistics = ParseStatistics.objects.filter(
                enable=True,
                contest__start_time__lte=now,
                contest__end_time__gte=now,
            )
            parse_statistics = parse_statistics.select_related('contest')

            for parse_stat in parse_statistics:
                now = timezone.now()
                if parse_stat.parse_time and parse_stat.parse_time > now:
                    self.logger.info(f'Skip {parse_stat.contest}, delay = {parse_stat.parse_time - now}')
                    continue
                self.logger.info(f'Parse statistic for {parse_stat.contest}')
                parse_stat.parse_time = now + parse_stat.delay
                parse_stat.save(update_fields=['parse_time'])
                if args.dryrun:
                    continue
                call_command(
                    'parse_statistic',
                    contest_id=parse_stat.contest.pk,
                    without_set_coder_problems=parse_stat.without_set_coder_problems,
                    without_stage=parse_stat.without_stage,
                    without_subscriptions=parse_stat.without_subscriptions,
                )

            parse_times = [p.parse_time for p in parse_statistics]
            if not parse_times:
                break

            parse_time = min(parse_times)
            delay = (parse_time - now).total_seconds()
            self.logger.info(f'Delay = {humanize.naturaldelta(delay)}, next parse time = {parse_time}')
            time.sleep(delay)

        # if not re.match(r'^-?\d+$', args.tid):
        #     tg_chat_id = Chat.objects.get(title=args.tid).chat_id
        # else:
        #     tg_chat_id = args.tid

        # bot = Bot()

        # if args.dump is not None and os.path.exists(args.dump):
        #     with open(args.dump, 'r') as fo:
        #         standings = json.load(fo)
        # else:
        #     standings = {}

        # problems_info = standings.setdefault('__problems_info', {})

        # iteration = 1 if args.dump else 0
        # forced_iterations = args.force_iterations

        # console = Console()

        # while True:
        #     subprocess.call('clear', shell=True)
        #     now = timezone.now()
        #     print(now)

        #     if not args.no_parse_statistic:
        #         call_command('parse_statistic', contest_id=args.cid, without_set_coder_problems=True)
        #     contest = Contest.objects.get(pk=args.cid)
        #     resource = contest.resource
        #     qs = Statistics.objects.filter(contest=contest)
        #     qs = qs.prefetch_related('account')
        #     statistics = list(qs)

        #     for p in problems_info.values():
        #         if p.get('accepted') or not p.get('n_hidden'):
        #             p.pop('show_hidden', None)
        #         p['n_hidden'] = 0

        #     updated = False
        #     has_hidden = contest.has_hidden_results
        #     numbered = 0
        #     table = Table()
        #     table.add_column('Rank')
        #     table.add_column('Score')
        #     table.add_column('Text')
        #     table.add_column('Pk')

        #     def statistics_sort_key(stat):
        #         return (
        #             stat.place_as_int if stat.place_as_int is not None else float('inf'),
        #             -stat.solving,
        #         )

        #     if args.coder_list:
        #         accounts_filter = CoderList.accounts_filter(uuids=[args.coder_list])
        #         qs = resource.account_set.filter(accounts_filter)  # TODO filter by contest
        #         coder_list_accounts = set(qs.values_list('pk', flat=True))

        #     for stat in sorted(statistics, key=statistics_sort_key):
        #         name_instead_key = resource.info.get('standings', {}).get('name_instead_key')
        #         name_instead_key = stat.account.info.get('_name_instead_key', name_instead_key)

        #         if name_instead_key:
        #             name = stat.account.name
        #         else:
        #             name = stat.addition.get('name')
        #             if not name or not has_season(stat.account.key, name):
        #                 name = stat.account.key

        #         stat_problems = stat.addition.get('problems', {})

        #         filtered = False
        #         if args.query is not None and re.search(args.query, name, re.I):
        #             filtered = True
        #         if args.top and stat.place_as_int and stat.place_as_int <= args.top and stat_problems:
        #             filtered = True
        #         if args.coder_list and stat.account.pk in coder_list_accounts:
        #             filtered = True

        #         contest_problems = contest.info.get('problems')
        #         division = stat.addition.get('division')
        #         if division and 'division' in contest_problems:
        #             contest_problems = contest_problems['division'][division]
        #         contest_problems = {get_problem_short(p): p for p in contest_problems}

        #         key = str(stat.account.id)
        #         standings_key = standings.get(key, {})
        #         problems = standings_key.get('problems', {})
        #         message_id = standings_key.get('message_id')
        #         message_text = standings_key.get('message_text', '')
        #         skip_in_message_text = True

        #         def delete_message():
        #             nonlocal message_id
        #             if message_id:
        #                 for it in range(3):
        #                     try:
        #                         bot.delete_message(chat_id=tg_chat_id, message_id=message_id)
        #                         message_id = None
        #                         break
        #                     except telegram.error.BadRequest as e:
        #                         logger.warning(str(e))
        #                         if 'Message to delete not found' in str(e):
        #                             break
        #                         raise e
        #                     except telegram.error.TimedOut as e:
        #                         logger.warning(str(e))
        #                         time.sleep(it)
        #                         continue

        #         p = []
        #         has_update = False
        #         has_first_ac = False
        #         has_max_score = False
        #         has_try_first_ac = False
        #         has_top = False
        #         has_solving_diff = (
        #             'solving' not in standings_key or
        #             abs(standings_key['solving'] - stat.solving) > 1e-9
        #         )

        #         in_time = None

        #         for k, v in stat_problems.items():
        #             if 'result' not in v:
        #                 continue

        #             p_info = problems_info.setdefault(k, {})
        #             p_result = problems.get(k, {}).get('result')
        #             p_verdict = problems.get(k, {}).get('verdict')
        #             result = v['result']
        #             verdict = v.get('verdict')

        #             is_hidden = str(result).startswith('?')
        #             is_accepted = str(result).startswith('+') or v.get('binary', False)
        #             try:
        #                 is_accepted = is_accepted or float(result) > 0 and not v.get('partial')
        #             except Exception:
        #                 pass
        #             is_max_score = False
        #             try:
        #                 is_max_score = float(result) > p_info.get('max_score', 0)
        #             except Exception:
        #                 pass

        #             if is_hidden:
        #                 p_info['n_hidden'] = p_info.get('n_hidden', 0) + 1

        #             has_change = p_result != result or (p_verdict and verdict and p_verdict != verdict)
        #             if has_change or is_hidden:
        #                 short = k
        #                 contest_problem = contest_problems.get(k, {})
        #                 if contest_problem and ('short' not in contest_problem or short != get_problem_short(contest_problem)):  # noqa
        #                     short = get_problem_name(contest_problems[k])
        #                     short = md_escape(short)
        #                 if 'url' in contest_problem:
        #                     short = '[%s](%s)' % (short, contest_problem['url'])

        #                 m = '%s%s `%s`' % (short, ('. ' + v['name']) if 'name' in v else '', scoreformat(result))

        #                 if verdict:
        #                     m += ' ' + md_escape(verdict)

        #                 if has_change:
        #                     if p_result is not None and v.get('partial'):
        #                         delta = as_number(result) - (as_number(p_result) or 0)
        #                         m += " `%s%s`" % ('+' if delta >= 0 else '', delta)

        #                     if in_time is None or solution_time_compare(in_time, v) < 0:
        #                         in_time = v

        #                     if verdict not in ['U']:
        #                         skip_in_message_text = False

        #                     has_update = True
        #                     if iteration:
        #                         if p_info.get('show_hidden') == key:
        #                             delete_message()
        #                             if not is_hidden:
        #                                 p_info.pop('show_hidden')
        #                         if not p_info.get('accepted'):
        #                             if is_accepted:
        #                                 m += ' FIRST ACCEPTED'
        #                                 has_first_ac = True
        #                             elif is_max_score:
        #                                 m += ' MAX SCORE'
        #                                 has_max_score = True
        #                             elif is_hidden and not p_info.get('show_hidden'):
        #                                 p_info['show_hidden'] = key
        #                                 m += ' TRY FIRST AC'
        #                                 has_try_first_ac = True
        #                     if args.top and stat.place_as_int and stat.place_as_int <= args.top:
        #                         has_top = True
        #                 p.append(m)
        #             if is_accepted:
        #                 p_info['accepted'] = True
        #             if is_max_score:
        #                 p_info['max_score'] = float(result)
        #             has_hidden = has_hidden or is_hidden

        #         prev_place_as_int = standings_key.get('place_as_int')
        #         place_as_int = stat.place_as_int
        #         if prev_place_as_int and place_as_int and prev_place_as_int > place_as_int:
        #             has_update = True
        #         prev_place = standings_key.get('place')
        #         place = stat.place
        #         if has_solving_diff and prev_place:
        #             place = '%s->%s' % (prev_place, place)
        #         if args.numbered is not None and re.search(args.numbered, stat.account.key, re.I):
        #             numbered += 1
        #             place = '%s (%s)' % (place, numbered)

        #         prefix_msg = ''
        #         if place is not None:
        #             prefix_msg += '`%s`. ' % place
        #         if in_time and 'time' in in_time:
        #             prefix_msg = '`[%s]` %s' % (in_time['time'], prefix_msg)

        #         account_url = reverse('coder:account', kwargs={'key': stat.account.key, 'host': resource.host})
        #         account_url = settings.MAIN_HOST_URL_ + md_url(account_url)
        #         account_msg = '[%s](%s)' % (name, account_url)
        #         if stat.account.country:
        #             account_msg = flag.flag(stat.account.country.code) + account_msg

        #         suffix_msg = ''
        #         if has_solving_diff:
        #             suffix_msg += ' = `%d`' % stat.solving
        #             if 'penalty' in stat.addition:
        #                 suffix_msg += rf' `[{stat.addition["penalty"]}]`'
        #         if p:
        #             suffix_msg += ' (%s)' % ', '.join(p)
        #         if has_top:
        #             suffix_msg += f' TOP{args.top}'

        #         if has_update or has_first_ac or has_try_first_ac or has_max_score:
        #             updated = True

        #         msg = prefix_msg + account_msg + suffix_msg
        #         history_msg = prefix_msg.rstrip() + suffix_msg

        #         if filtered:
        #             table.add_row(str(stat.place), str(stat.solving), Markdown(msg), str(stat.pk))
        #         if not args.dryrun and (filtered and has_update or has_first_ac or has_try_first_ac or has_max_score):
        #             if args.with_history:
        #                 delete_message()
        #                 msg = combine_messages(msg, message_text)
        #             n_attempts = 5
        #             delay_on_timeout = 3
        #             for it in range(n_attempts):
        #                 try:
        #                     message = bot.send_message(msg=msg, chat_id=tg_chat_id)
        #                     message_id = message.message_id
        #                     break
        #                 except telegram.error.TimedOut as e:
        #                     logger.warning(str(e))
        #                 except telegram.error.BadRequest as e:
        #                     logger.error(str(e))
        #                 wait('send message', it * delay_on_timeout)
        #             if not skip_in_message_text:
        #                 message_text = combine_messages(history_msg, message_text)

        #         if args.with_subscriptions:
        #             has_subscription_update = stat.account.n_subscribers and has_update
        #             if has_subscription_update:
        #                 subscriptions_filter = (
        #                     Q(accounts=stat.account)
        #                     & (Q(resource__isnull=True) | Q(resource=resource))
        #                     & (Q(contest__isnull=True) | Q(contest=contest))
        #                 )
        #                 subscriptions = Subscription.objects.filter(subscriptions_filter)
        #                 for subscription in subscriptions:
        #                     subscription.send(message=msg)

        #         data = {
        #             'solving': stat.solving,
        #             'place': stat.place,
        #             'place_as_int': stat.place_as_int,
        #             'problems': stat.addition.get('problems', {}),
        #             'message_id': message_id,
        #             'message_text': message_text,
        #         }
        #         standings[key] = data

        #     console.print(table)

        #     if args.dump is not None and (updated or not os.path.exists(args.dump)):
        #         standings_dump = json.dumps(standings, indent=2)
        #         with open(args.dump, 'w') as fo:
        #             fo.write(standings_dump)

        #     if iteration:
        #         is_over = contest.end_time < now or contest.time_percentage >= 1
        #         if args.no_parse_statistic or forced_iterations <= 0 and is_over and not has_hidden:
        #             break
        #         is_coming = now < contest.standings_start_time
        #         if is_coming:
        #             limit = contest.standings_start_time
        #         else:
        #             tick = args.delay * 10 if is_over else args.delay
        #             limit = now + timedelta(seconds=tick)
        #         wait('parsing iteration', limit)

        #     iteration += 1
        #     forced_iterations -= 1
