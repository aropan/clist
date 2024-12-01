#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import json
import logging
import re
import shlex
from itertools import chain
from traceback import format_exc

import pytz
import telegram
from django.conf import settings
from django.db.models import Prefetch, Q
from django.urls import reverse
from django.utils.timezone import now
from pytimeparse.timeparse import timeparse
from sql_util.utils import SubqueryCount
from telegram.constants import MAX_MESSAGE_LENGTH

from clist.api.v2 import ContestResource
from clist.models import Contest, Resource
from clist.templatetags.extras import as_number, hr_timedelta, md_escape, md_url, md_url_text
from notification.models import Subscription
from notification.utils import compose_message_by_problems
from ranking.models import ParseStatistics, Statistics
from tg.models import Chat, History

logging.basicConfig(level=logging.DEBUG)


class ArgumentParserError(Exception):
    pass


class ArgumentCommandError(Exception):
    pass


class NeedHelpError(Exception):
    pass


class IncomingError(Exception):
    pass


class ThrowingArgumentParser(argparse.ArgumentParser):
    def exit(self, status=0, message=0):
        raise NeedHelpError(self.format_help())

    def error(self, message):
        if 'argument command: invalid choice' in message:
            raise ArgumentCommandError(message)
        raise ArgumentParserError(message)


def escape(*args):
    if len(args) == 1:
        return md_escape(args[0])
    return tuple(map(md_escape, args))


class Bot(telegram.Bot):
    ADMIN_CHAT_ID = settings.TELEGRAM_ADMIN_CHAT_ID

    def __init__(self, *args, **kw):
        if settings.TELEGRAM_TOKEN is not None:
            super().__init__(settings.TELEGRAM_TOKEN, *args, **kw)
        self.logger = logging.getLogger('telegrambot')
        self.logger.setLevel(logging.DEBUG)

    @property
    def chat(self):
        if not hasattr(self, 'chat_'):
            self.chat_ = Chat.objects.filter(chat_id=self.from_id).first()
        return self.chat_

    @property
    def group(self):
        if not hasattr(self, 'group_'):
            if self.chat and self.chat.chat_id != self.chat_id:
                self.group_ = Chat.objects.filter(chat_id=self.chat_id, thread_id=self.thread_id).first()
            else:
                self.group_ = False
        return self.group_

    @property
    def coder(self):
        if not hasattr(self, 'coder_'):
            self.coder_ = self.chat.coder if self.chat else None
        return self.coder_

    def clear_cache(self):
        for a in ('chat_', 'group_', 'coder_'):
            if hasattr(self, a):
                delattr(self, a)

    def update_chat_info(self, chat, message):
        if not chat:
            return

        message_from = self.message.get('from', {})
        for k in ('username', 'id', ):
            if k in message_from:
                title = '@' + str(message_from[k])
                if title != chat.title:
                    chat.title = title
                    chat.save(update_fields=['title'])
                break

        names = []
        for k in 'first_name', 'last_name':
            if k in message_from:
                names.append(message_from[k])
        name = ' '.join(names).strip()
        if name and name != chat.name:
            chat.name = name
            chat.save(update_fields=['name'])

    def start(self, args):
        success = False
        if args.key:
            chat = Chat.objects.filter(secret_key=args.key).first()
            if not chat:
                if self.coder:
                    yield 'Hmm, you are already connected.'
                else:
                    yield 'We having problems. Key "%s" can not be found.' % escape(args.key)
            else:
                qs = Chat.objects.filter(chat_id=self.from_id).filter(~Q(secret_key=args.key))
                if qs.count():
                    chat.delete()
                    yield 'Oops, chat id are already connected to %s.' % (qs[0].coder.user.username)
                    return
                chat.chat_id = self.from_id
                self.update_chat_info(chat, self.message)
                chat.save()
                self.chat_ = chat
                self.coder_ = chat.coder
                success = True

        if self.coder:
            yield 'Hi, %s.' % escape(self.coder.user.username)
        if success:
            yield 'Successfully connected. Now you can see /help.'

    def help(self, args):
        yield 'Here\'s what I can do:\n' + ';\n'.join(
            '%s _%s_' % escape(choice, subparser.description)
            for s in self.parser._subparsers._actions
            if isinstance(s, argparse._SubParsersAction)
            for choice, subparser in list(s.choices.items())
        ) + '.' + '\n\n' + '*You can also use command with --help for more information.*'
        if self.chat and self.chat.chat_id == str(self.ADMIN_CHAT_ID):
            yield self.get_commands()

    def list(self, args):
        if not getattr(args, 'ignore_filters', False):
            if self.group:
                filter_ = self.group.coder.get_contest_filter(self.group.chat_id)
            else:
                filter_ = self.coder.get_contest_filter('telegram') if self.coder else Q()
        else:
            filter_ = Q()
        if args.query:
            queries = {}
            for q in args.query:
                k, v = q.split("=", 1)
                if k.startswith('duration'):
                    v = int(v) if v.isdigit() else timeparse(v)
                queries[k] = v
            queries['order_by'] = 'event'
            filter_ &= Q(**ContestResource().build_filters(queries))

        if args.grep:
            filter_ &= (Q(title__iregex=args.grep) | Q(resource__host__iregex=args.grep))

        time = now()

        if args.coming:
            filter_ &= Q(start_time__gte=time)

        qs = Contest.visible.filter(end_time__gte=time).filter(filter_)

        first = args.offset
        last = args.offset + args.limit

        total = None
        if args.sort_by:
            s = args.sort_by
            s = ContestResource.base_fields[s].attribute
            s = ('-' if args.reverse_sort else '') + s
            total = qs.count()
            qs = qs.order_by(s)
            qs = qs[first:last]
        else:
            fs = qs.filter(start_time__lte=time).order_by('end_time', 'id')
            sc = qs.filter(start_time__gt=time).order_by('start_time', 'id')
            total = fs.count()
            fs = fs[first:last]
            first -= total
            last -= total
            total += sc.count()
            if last > 0:
                sc = sc[max(first, 0):last]
                qs = chain(fs, sc)
            else:
                qs = fs

        time_format = escape(args.time_format)
        result = []
        for c in qs:
            d = {
                'label': escape(args.label[0 if time < c.start_time else (1 if time < c.end_time else 2)]),
                'resource': c.resource.host,
                'event': escape(c.title),
                'start': c.start_time.astimezone(self.tz).strftime(time_format),
                'end': c.end_time.astimezone(self.tz).strftime(time_format),
                'remaining': hr_timedelta(c.next_time),
                'duration': c.hr_duration,
                'href': c.url,
            }
            result.append(args.format % d)

        if not result:
            yield 'Nothing was found, sure that something be?'
            return

        result = args.delimiter.join(result)

        num_pages = (total + args.limit - 1) / args.limit
        if not args.no_paging and num_pages > 1:
            no_page = args.offset / args.limit + 1
            result += args.delimiter + '%d of %d' % (no_page, num_pages)
            setattr(args, 'paging__', {'no_page': no_page, 'num_pages': num_pages})

        yield result

    @property
    def tzname(self):
        return self.coder.timezone if self.coder else settings.DEFAULT_TIME_ZONE_

    @property
    def tz(self):
        return pytz.timezone(self.tzname)

    def time(self, args):
        yield now().astimezone(self.tz).strftime('%A, %H:%M:%S%z')

    def resources(self, args):
        qs = Resource.objects.all()
        if args.grep:
            qs = qs.filter(host__iregex=args.grep)
        result = args.delimiter.join('[{0.host}](http://{0.host}]/)'.format(r) for r in qs)
        yield result

    def iamadmin(self, args):
        if not self.coder:
            return
        if self.group is False:
            msg = 'This command should be used in chat rooms.'
        else:
            if self.group is None:
                title = self.message['chat']['title']
                if self.thread_id:
                    title += f' # {self.thread_name}'
                chat, created = Chat.objects.get_or_create(
                    chat_id=self.chat_id,
                    thread_id=self.thread_id,
                    coder=self.coder,
                    title=title,
                    is_group=True,
                )
                if created:
                    msg = '%s is new admin @%s for "%s".' % (self.coder.user, settings.TELEGRAM_NAME, chat.title)
                    delattr(self, 'group_')
                else:
                    msg = 'Hmmmm, problem with set new admin.'
            else:
                msg = 'Group "%s" already has %s admin.' % (self.message['chat']['title'], self.group.coder.user)
        yield msg

    def iamnotadmin(self, args):
        if not self.coder:
            return
        if self.group is False:
            msg = 'This command should be used in chat rooms.'
        else:
            if self.group is None or self.group.coder != self.coder:
                msg = '%s has unsuccessful attempt to lose admin.' % (self.coder.user)
            else:
                self.group.delete()
                msg = '%s has successful attempt to lose admin.' % (self.coder.user)
                self.group_ = None
        yield msg

    def join(self, args):
        if not self.coder:
            return
        if self.group is None:
            msg = 'Select admin before join.'
        elif self.group is False:
            msg = 'This command should be used in chat rooms.'
        elif self.group.coders.filter(pk=self.coder.pk).first():
            msg = f'You are already joined "{self.group.title}".'
        else:
            self.group.coders.add(self.coder)
            msg = f'You joined "{self.group.title}".'
        yield msg

    def leave(self, args):
        if not self.coder:
            return
        if not self.group or not self.group.coders.filter(pk=self.coder.pk).first():
            msg = 'Join telegram group before leave.'
        else:
            self.group.coders.remove(self.coder)
            msg = f'You left "{self.group.title}".'
        yield msg

    def unlink(self, args):
        if not self.coder or self.group or not self.chat:
            yield 'Unsuitable moment.'
        else:
            yield 'Bye Bye.'
            self.chat.delete()
            self.chat_ = False

    def subscribe(self, args):

        n_aggregated = 0
        aggregated_msg = None

        def messaging(msg):
            nonlocal aggregated_msg, n_aggregated
            if not aggregated_msg:
                n_aggregated = 0
            if n_aggregated == 20 or len(aggregated_msg) + len(msg) + 1 >= MAX_MESSAGE_LENGTH:
                yield aggregated_msg
                aggregated_msg = ''
                n_aggregated = 0
            if aggregated_msg:
                aggregated_msg += '\n'
            aggregated_msg += msg
            n_aggregated += 1

        def show_subscribed(method):
            nonlocal aggregated_msg
            subscriptions = Subscription.objects.filter(coder=self.coder, method=method, contest__isnull=False)
            subscriptions = subscriptions.select_related('contest')
            subscriptions = subscriptions.annotate(n_accounts=SubqueryCount('accounts'))
            if subscriptions:
                aggregated_msg = ''
                yield from messaging('Subscribed contests:')
                for subscription in subscriptions:
                    contest = subscription.contest
                    message = (f'[{contest.title}]({md_url(contest.actual_url)}) `{contest.pk}` '
                               f', {subscription.n_accounts} account(s)' +
                               (f' + top {subscription.top_n}' if subscription.top_n else '') +
                               (' + first ac' if subscription.with_first_accepted else ''))
                    yield from messaging(message)
                yield aggregated_msg

        if not self.is_private:
            chat = self.group or self.chat
            if not chat or chat.coder != self.coder:
                yield 'Use /iamadmin before subscribe.'
                return

        method = 'telegram'
        if not self.coder or not self.is_private:
            method += f':{self.chat_id}'
            if self.thread_id:
                method += f':{self.thread_id}'

        if args.contest:
            contest = Contest.get(args.contest)
        else:
            contest = ParseStatistics.relevant_contest()
        if not contest:
            if args.contest:
                yield f'Contest "{args.contest}" not found.'
            else:
                yield 'No set contest. Use `-c` or `--contest` option to choose contest.'
                yield from show_subscribed(method)
            return

        contest_msg = f'[{contest.title}]({md_url(contest.actual_url)}) `{contest.pk}`'
        if args.show:
            yield f'Current contest: {contest_msg}.'
            yield from show_subscribed(method)
            return

        subscription, created = Subscription.objects.get_or_create(coder=self.coder, contest=contest, method=method)
        if created:
            method_chat = f'telegram:{self.chat_id}'
            already_subscriptions = Subscription.objects.filter(Q(coder__isnull=False, coder=self.coder) |
                                                                Q(method=method_chat) |
                                                                Q(method__startswith=f'{method_chat}:'))
            n_subscriptions_limit = settings.CODER_N_SUBSCRIPTIONS_LIMIT_
            if already_subscriptions.count() > n_subscriptions_limit:
                subscription.delete()
                yield (f'You have reached the limit of {n_subscriptions_limit} subscriptions.\n'
                       f'Remove unnecessary subscriptions with `-r` or `--remove` options.')
                return

        if args.list:
            if subscription.is_empty():
                subscription.delete()
                yield 'No subscribed participants.'
                return
            accounts = subscription.accounts.all()
            statistics_prefetch = Prefetch('statistics_set',
                                           queryset=Statistics.objects.filter(contest=contest),
                                           to_attr='contest_statistics')
            accounts = accounts.prefetch_related(statistics_prefetch)

            statistics_filter = Q(account__in=accounts)
            if subscription.top_n:
                statistics_filter |= Statistics.top_n_filter(subscription.top_n)
            if subscription.with_first_accepted:
                statistics_filter |= Statistics.first_ac_filter()
            contest_statistics = Statistics.objects.filter(contest=contest).filter(statistics_filter)
            contest_statistics = contest_statistics.select_related('account', 'contest__resource')
            contest_statistics = contest_statistics.order_by('place_as_int', 'pk')

            aggregated_msg = ''
            seen_accounts = set()
            for stat in contest_statistics:
                account_msg = compose_message_by_problems([], stat,  {}, contest)
                yield from messaging(account_msg)
                seen_accounts.add(stat.account_id)
            for account in accounts:
                if account.pk in seen_accounts:
                    continue
                account_msg = f'[{md_url_text(account.display())}]({md_url(account.url)})'
                yield from messaging(account_msg)
            yield aggregated_msg
            return

        skip_names_info = False

        if args.first_ac is not None:
            skip_names_info = True
            first_ac_msg = 'subscribed to first accepted' if args.first_ac else 'unsubscribed from first accepted'
            if subscription.with_first_accepted != args.first_ac:
                subscription.with_first_accepted = args.first_ac
                subscription.save(update_fields=['with_first_accepted'])
                first_ac_msg = first_ac_msg.capitalize()
            else:
                first_ac_msg = f'Already {first_ac_msg}'
            yield f'{first_ac_msg} for {contest_msg}.'

        if args.top_n is not None:
            skip_names_info = True
            args.top_n = args.top_n or None
            if args.top_n:
                if not 1 <= args.top_n <= settings.CODER_SUBSCRIPTION_TOP_N_LIMIT_:
                    yield rf'Top N should be in range \[1, {settings.CODER_SUBSCRIPTION_TOP_N_LIMIT_}].'
                    return
            top_n_msg = f'subscribed to top {args.top_n}' if args.top_n else 'unsubscribed from top'
            if subscription.top_n != args.top_n:
                subscription.top_n = args.top_n
                subscription.save(update_fields=['top_n'])
                top_n_msg = top_n_msg.capitalize()
            else:
                top_n_msg = f'Already {top_n_msg}'
            yield f'{top_n_msg} for {contest_msg}.'

        accounts_pk_set = set(subscription.accounts.values_list('pk', flat=True))
        processed = set()
        changed = False
        aggregated_msg = ''
        subscription_n_limit = settings.CODER_SUBSCRIPTION_N_LIMIT_
        for name in args.names:
            qs = Statistics.objects.filter(contest=contest)
            qs = qs.filter(Q(account__name__icontains=name) | Q(account__key__icontains=name))
            qs = qs.select_related('account')
            exact = any(statistic.account.name == name or statistic.account.key == name for statistic in qs)
            for statistic in qs.select_related('account'):
                account = statistic.account
                if exact and account.name != name and account.key != name:
                    continue
                if account in processed:
                    continue
                processed.add(account)
                account_msg = f'[{md_url_text(account.display())}]({md_url(account.url)})'
                if args.remove:
                    if account.pk in accounts_pk_set:
                        accounts_pk_set.remove(account.pk)
                        yield from messaging(f'Unsubscribed {account_msg}.')
                        changed = True
                else:
                    if account.pk not in accounts_pk_set:
                        if len(accounts_pk_set) >= subscription_n_limit:
                            yield from messaging(f'You have reached the limit of {subscription_n_limit} participants.')
                            break
                        accounts_pk_set.add(account.pk)
                        yield from messaging(f'Subscribed {account_msg}.')
                        changed = True
                    else:
                        yield from messaging(f'Already subscribed {account_msg}.')
        yield aggregated_msg

        if changed:
            subscription.accounts.set(accounts_pk_set)
        if subscription.is_empty():
            subscription.delete()
        if not args.names and args.remove:
            if subscription.pk:
                subscription.delete()
                yield f'Unsubscribed from all participants of {contest_msg}.'
            else:
                yield f'No subscribed participants for {contest_msg}.'
        elif not contest.n_statistics:
            if contest.is_coming():
                yield 'Contest has not started yet, please try again later.'
            else:
                yield 'Participant list is unavailable, please try again later.'
        elif skip_names_info:
            return
        elif not args.names:
            yield f'Set the names of participants for {contest_msg}.'
        elif not changed:
            yield f'Participants not found to change for {contest_msg}.'

    def unsubscribe(self, args):
        for action in self.subscribe_parser._actions:
            if action.dest == 'help' or action.dest in args:
                continue
            setattr(args, action.dest, action.default)
        args.remove = True
        yield from self.subscribe(args)

    @property
    def parser(self):
        if not hasattr(self, 'parser_'):
            self.parser_ = ThrowingArgumentParser(prog='ask me')
            command_p = self.parser_.add_subparsers(dest='command', help='Please to bot')

            start_p = command_p.add_parser('/start', description='Start communication and connect your account')
            start_p.add_argument('key', nargs='?', help='Connect account using secret key')

            command_p.add_parser('/time', description='Show current time in your timezone')

            resources_p = command_p.add_parser('/resources', description='View resources list')
            resources_p.add_argument('-g', '--grep', help='Grep host field')
            resources_p.add_argument('-d', '--delimiter', help='Events delimiter', default='\n')

            list_p = command_p.add_parser('/list', description='View contest list')
            list_p.add_argument('-g', '--grep', help='Grep by event and resource field')
            list_p.add_argument(
                '-f', '--format', help='Formating events',
                default='%(start)s - %(duration)s - %(remaining)s %(label)s\n[%(event)s](%(href)s) - `%(resource)s`',
            )
            list_p.add_argument('-t', '--time-format', help='Formating time', default='%d.%m %a %H:%M')
            list_p.add_argument('-d', '--delimiter', help='Events delimiter', default='\n\n')
            list_p.add_argument('-q', '--query', help='Query filter', action='append')
            list_p.add_argument('-s', '--sort-by', help='Sorting by field', choices=ContestResource.Meta.ordering)
            list_p.add_argument('-r', '--reverse-sort', help='Reversing sort by field',  action='store_true')
            list_p.add_argument('-o', '--offset', help='Offset start slice', type=int, default=0)
            list_p.add_argument('-l', '--limit', help='Limit slice', type=int, default=10)
            list_p.add_argument('-c', '--coming', help='Only coming events', action='store_true')
            list_p.add_argument('-lb', '--label', help='Labeling contest chars', nargs=3,
                                default=['', '[running]', '[past]'])
            list_p.add_argument('-np', '--no-paging', help='Paging view', action='store_true')
            list_p.add_argument('-i', '--ignore-filters', help='Ignore filters', action='store_true')

            command_p.add_parser('/iamadmin', description='Set user as admin clistbot for group')
            command_p.add_parser('/iamnotadmin', description='Unset user as admin clistbot for group')

            command_p.add_parser('/join', description='Join telegram group')
            command_p.add_parser('/leave', description='Leave telegram group')

            command_p.add_parser('/unlink', description='Unlink account')

            subscribe_p = command_p.add_parser('/subscribe', description='Subscribe to participants')
            subscribe_p.add_argument('names', metavar='NAME', nargs='*',
                                     help='Participants names (partial matches allowed). '
                                     'Double quote names with spaces')
            subscribe_p.add_argument('-c', '--contest', help='Contest id, series, name or host')
            subscribe_p.add_argument('-fa', '--first-ac', action='store_true',
                                     help='Subscribe to first accepted', default=None)
            subscribe_p.add_argument('-nofa', '--no-first-ac', dest='first_ac', action='store_false',
                                     help='Unsubscribe to first accepted')
            subscribe_p.add_argument('-tn', '--top-n', type=int, metavar='N',
                                     help='Subscribe to top N. Set 0 to unsubscribe top')
            subscribe_p.add_argument('-r', '--remove', action='store_true',
                                     help='Remove subscription or specified participants if specified')
            subscribe_p.add_argument('-l', '--list', action='store_true', help='List subscribed participants')
            subscribe_p.add_argument('-s', '--show', action='store_true', help='Show current contest and subscriptions')
            self.subscribe_parser = subscribe_p

            unsubscribe_p = command_p.add_parser('/unsubscribe', description='Unsubscribe from participants')
            unsubscribe_p.add_argument('names', metavar='NAME', nargs='*',
                                       help='Participants names (partial matches allowed). '
                                       'Double quote names with spaces')
            unsubscribe_p.add_argument('-c', '--contest', help='Contest id, series or name')

            for a in list_p._actions:
                if not isinstance(a, argparse._HelpAction):
                    if a.default is not None:
                        d = str(a.default).replace('\n', r'\n')
                        a.help = a.help + '. Default: "%s"' % d.replace('%', '%%')

            command_p.add_parser('/prev', description='Show previous page in paging')
            command_p.add_parser('/next', description='Show next page in paging')
            command_p.add_parser('/repeat', description='Repeat last command')

            command_p.add_parser('/help', description='Show what I can do')

        return self.parser_

    def execute_command(self, raw_query):
        try:
            query = raw_query.replace("\u2014", "--")
            regex = '|'.join(
                choice for s in self.parser._subparsers._actions
                if isinstance(s, argparse._SubParsersAction)
                for choice in list(s.choices.keys())
            )
            regex = '(^%s)@%s' % (regex, settings.TELEGRAM_NAME)
            query = re.sub(regex, r'\1', query)
            args = self.parser.parse_args(shlex.split(query))
            if args.command in ['/prev', '/next', '/repeat']:
                if not self.chat or not self.chat.last_command:
                    yield 'Not found previous command'
                    return
                c = args.command
                dargs = vars(args)
                dargs.update(self.chat.last_command)

                self.chat_id = dargs.pop('chat_id__', self.chat.chat_id)
                if hasattr(self, 'group_'):
                    delattr(self, 'group_')

                if c != '/repeat':
                    if 'offset' not in dargs or 'limit' not in args:
                        yield 'Command does not support paging.'
                        return
                    if c == '/prev':
                        args.offset = max(args.offset - args.limit, 0)
                    elif c == '/next':
                        args.offset = args.offset + args.limit

            self.logger.info('args = %s' % args)
            if self.chat:
                dargs = vars(args)
                dargs['chat_id__'] = self.chat_id
                self.chat.last_command = dargs
                self.chat.save(update_fields=['last_command'])

            for msg in getattr(self, args.command[1:])(args):
                paging = getattr(args, 'paging__', False)
                if paging:
                    buttons = []
                    no_page = paging.get('no_page', None)
                    if no_page != 1:
                        buttons.append('/prev')
                    if no_page != paging.get('num_pages', 0):
                        buttons.append('/next')
                    yield {
                        'text': msg,
                        'reply_markup': telegram.ReplyKeyboardMarkup([buttons], resize_keyboard=True),
                    }
                else:
                    yield msg

            try:
                if self.group or self.chat_type in ['group', 'supergroup', 'channel']:
                    self.delete_message(self.message['chat']['id'], self.message['message_id'])
            except telegram.error.BadRequest:
                pass
        except (ArgumentParserError, ArgumentCommandError) as e:
            yield 'Could you please clarify:\n' + escape(str(e))
        except NeedHelpError as e:
            yield 'If you need help, please:\n```help\n' + str(e) + '\n```'
        except Exception as e:
            self.sendMessage(self.ADMIN_CHAT_ID, 'Query: %s\n\n%s' % (raw_query, format_exc()))
            yield 'Oops, I\'m having a little trouble:\n' + escape(str(e))

    def send_message(self, msg, chat_id=None, reply_markup=None):
        if not isinstance(msg, dict):
            msg = {'text': msg}
        if not msg['text']:
            return
        if len(msg['text']) > MAX_MESSAGE_LENGTH:
            msg['text'] = msg['text'][:MAX_MESSAGE_LENGTH - 3] + '...'

        chat_id = chat_id or self.from_id
        if ':' in chat_id:
            chat_id, thread_id = chat_id.split(':', 1)
            thread_id = as_number(thread_id)
            if thread_id is not None:
                msg['reply_to_message_id'] = thread_id
        msg['chat_id'] = chat_id

        msg['disable_web_page_preview'] = True
        if reply_markup:
            msg['reply_markup'] = reply_markup
        if 'reply_markup' not in msg:
            msg['reply_markup'] = telegram.ReplyKeyboardRemove()

        chat_type = getattr(self, 'chat_type', None)
        if reply_markup is False or chat_type is None or chat_type in ['group', 'supergroup', 'channel']:
            msg.pop('reply_markup', None)

        try:
            ret = self.sendMessage(parse_mode='Markdown', **msg)
        except Exception as e:
            self.logger.warning(f'message = {msg}')
            self.logger.error(f'Exception send message {e}')
            if "can't parse entities" in str(e).lower():
                ret = self.sendMessage(**msg)
            else:
                raise e
        return ret

    def admin_message(self, msg):
        return self.send_message(msg, chat_id=self.ADMIN_CHAT_ID)

    @property
    def follow_url(self):
        return settings.HTTPS_HOST_URL_ + reverse('telegram:me')

    def incoming(self, raw_data):
        try:
            data = json.loads(raw_data)
            self.logger.info('incoming = \n%s' % json.dumps(data, indent=2))

            if 'from' in data.get('message', {}):
                self.message = data['message']
                self.from_id = str(self.message['from']['id'])
            elif 'forward_from' in data.get('channel_post', {}):
                self.message = data['channel_post']
                self.from_id = str(self.message['forward_from']['id'])
            elif 'sender_chat' in data.get('channel_post', {}):
                self.message = data['channel_post']
                self.from_id = str(self.message['sender_chat']['id'])
            else:
                return

            self.chat_id = str(self.message['chat']['id'])
            self.chat_type = self.message['chat'].get('type')
            self.is_private = self.chat_type == 'private'

            if self.message.get('is_topic_message'):
                thread = self.message.get('reply_to_message', {}).get('forum_topic_created')
                if thread:
                    self.thread_id = str(self.message['message_thread_id'])
                    self.thread_name = thread['name']

            self.thread_id = str(self.message.get('message_thread_id', '')) or None

            self.update_chat_info(self.chat, self.message)

            self.clear_cache()

            was_messaging = False
            has_command = False
            if 'text' in self.message:
                text = self.message['text']
                if text.startswith('/'):
                    has_command = True
                    for msg in self.execute_command(text):
                        self.send_message(msg)
                        was_messaging = True
            if not has_command and self.chat and self.chat.settings.get('_forwarding'):
                self.forwardMessage(
                    chat_id=self.chat.settings.get('_forwarding'),
                    from_chat_id=self.from_id,
                    message_id=self.message['message_id'],
                )

            if self.coder and not was_messaging and self.coder.settings.get('telegram', {}).get('unauthorized', False):
                self.coder.settings.setdefault('telegram', {})['unauthorized'] = False
                self.coder.save(update_fields=['settings'])
            chat = self.group or self.chat
            if chat:
                History.objects.create(chat=chat, message=data).save()
        except Exception as e:
            self.logger.info('Exception incoming message:\n%s\n%s' % (format_exc(), raw_data))
            self.logger.error(f'Exception incoming message: {e}')
            try:
                self.sendMessage(
                    self.ADMIN_CHAT_ID,
                    'What need from me?',
                    reply_to_message_id=self.message['message_id'],
                )
            except Exception:
                pass
            if hasattr(self, 'from_id'):
                self.sendMessage(self.from_id, 'Thanks, but I do not know what I should do about it.')

    def get_commands(self):
        return '\n'.join(
            '%s - %s' % (choice[1:], subparser.description)
            for s in self.parser._subparsers._actions
            if isinstance(s, argparse._SubParsersAction)
            for choice, subparser in list(s.choices.items())
        )

    def get_help(self):
        return '#Help @' + settings.TELEGRAM_NAME + '\n\n' + '\n\n'.join(
            '##%s\n```\n#!text\n%s```' % (choice[1:], subparser.format_help())
            for s in self.parser._subparsers._actions
            if isinstance(s, argparse._SubParsersAction)
            for choice, subparser in list(s.choices.items())
        )

    def webhook(self):
        url = settings.HTTPS_HOST_URL_ + reverse('telegram:incoming')
        self.logger.info('webhook url = %s' % url)
        return self.setWebhook(url)

    def unwebhook(self):
        self.logger.info('unwebhook')
        return self.setWebhook(None)
