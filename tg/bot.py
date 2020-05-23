#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging

import telegram

from django.conf import settings
from django.utils.timezone import now
from django.urls import reverse
from django.db.models import Q

from tg.models import Chat, History
from clist.models import Contest, Resource
from clist.templatetags.extras import hr_timedelta, md_escape
from clist.api.v1 import ContestResource

import argparse
import shlex
from traceback import format_exc
import pytz
from pytimeparse.timeparse import timeparse
from itertools import chain
import json
import re


logging.basicConfig(level=logging.DEBUG)


class ArgumentParserError(Exception):
    pass


class NeedHelpError(Exception):
    pass


class IncomingError(Exception):
    pass


class ThrowingArgumentParser(argparse.ArgumentParser):
    def exit(self, status=0, message=0):
        raise NeedHelpError(self.format_help())

    def error(self, message):
        raise ArgumentParserError(message)


def escape(*args):
    if len(args) == 1:
        return md_escape(args[0])
    return tuple(map(md_escape, args))


class Bot(telegram.Bot):
    MAX_LENGTH_MESSAGE = 4096
    ADMIN_CHAT_ID = settings.TELEGRAM_ADMIN_CHAT_ID

    def __init__(self, *args, **kw):
        super(Bot, self).__init__(settings.TELEGRAM_TOKEN, *args, **kw)
        self.logger = logging.getLogger('telegrambot')
        self.logger.setLevel(logging.DEBUG)
        self.logger.info('Start')

    @property
    def chat(self):
        if not hasattr(self, 'chat_'):
            self.chat_ = Chat.objects.filter(chat_id=self.from_id).first()
        return self.chat_

    @property
    def group(self):
        if not hasattr(self, 'group_'):
            if self.chat and self.chat.chat_id != self.chat_id:
                self.group_ = Chat.objects.filter(chat_id=self.chat_id).first()
            else:
                self.group_ = False
        return self.group_

    @property
    def coder(self):
        if not hasattr(self, 'coder_'):
            self.coder_ = self.chat.coder if self.chat else None
        return self.coder_

    def clear_cache(self):
        for a in ('chat_', 'coder_'):
            if hasattr(self, a):
                delattr(self, a)

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
                for k in ('username', 'id', ):
                    if k in self.message['from']:
                        chat.title = '@' + str(self.message['from'][k])
                        break
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
                filter_ = self.group.coder.get_contest_filter(self.group.get_group_name())
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
            fs = qs.filter(start_time__lte=time).order_by('end_time')
            sc = qs.filter(start_time__gt=time).order_by('start_time')
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
            msg = 'This command is used in chat rooms'
        else:
            if self.group is None:
                chat, created = Chat.objects.get_or_create(
                    chat_id=self.chat_id,
                    coder=self.coder,
                    title=self.message['chat']['title'],
                    is_group=True,
                )
                if created:
                    msg = '%s is new admin @ClistBot for "%s"' % (self.coder.user, chat.title)
                else:
                    msg = 'Hmmmm, problem with set new admin'
            else:
                msg = 'Group "%s" already has %s admin' % (self.message['chat']['title'], self.group.coder.user)
            self.send_message(msg, chat_id=self.chat_id)
        yield msg

    def iamnotadmin(self, args):
        if not self.coder:
            return
        if self.group is False:
            msg = 'This command is used in chat rooms'
        else:
            if self.group is None:
                msg = '%s has unsuccessful attempt to lose admin' % (self.coder.user)
            else:
                self.group.delete()
                msg = '%s has successful attempt to lose admin' % (self.coder.user)
                self.group_ = None
            self.send_message(msg, chat_id=self.chat_id)
        yield msg

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
            list_p.add_argument('-l', '--limit', help='Limit slice', type=int, default=5)
            list_p.add_argument('-c', '--coming', help='Only coming events', action='store_true')
            list_p.add_argument('-lb', '--label', help='Labeling contest chars', nargs=3, default=['', '*', '[past]'])
            list_p.add_argument('-np', '--no-paging', help='Paging view', action='store_true')
            list_p.add_argument('-i', '--ignore-filters', help='Ignore filters', action='store_true')

            command_p.add_parser('/iamadmin', description='Set user as admin clistbot for group')
            command_p.add_parser('/iamnotadmin', description='Unset user as admin clistbot for group')

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
            regex = '(^%s)%s' % (regex, settings.TELEGRAM_NAME)
            query = re.sub(regex, r'\1', query)

            args = self.parser.parse_args(shlex.split(query))

            self.logger.info('args = %s' % args)
            if args.command in ['/prev', '/next', '/repeat']:
                if not self.chat or not self.chat.last_command:
                    yield 'Sorry, not found previous command'
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
                self.chat.save()

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
        except ArgumentParserError as e:
            yield 'I\'m sorry, could you clarify:\n' + escape(str(e))
        except NeedHelpError as e:
            yield 'If you need help, please:\n' + escape(str(e))
        except Exception as e:
            self.sendMessage(self.ADMIN_CHAT_ID, 'Query: %s\n\n%s' % (raw_query, format_exc()))
            yield 'Oops, I\'m having a little trouble:\n' + escape(str(e))

    def send_message(self, msg, chat_id=None):
        if not isinstance(msg, dict):
            msg = {'text': msg}
        if not msg['text']:
            return
        if len(msg['text']) > self.MAX_LENGTH_MESSAGE:
            msg['text'] = msg['text'][:self.MAX_LENGTH_MESSAGE - 3] + '...'

        msg['chat_id'] = chat_id or self.from_id

        msg['disable_web_page_preview'] = True
        if 'reply_markup' not in msg:
            msg['reply_markup'] = telegram.ReplyKeyboardRemove()

        try:
            ret = self.sendMessage(parse_mode='Markdown', **msg)
        except Exception:
            self.logger.error('Exception send message = %s' % msg)
            ret = self.sendMessage(**msg)
        return ret

    def admin_message(self, msg):
        return self.send_message(msg, chat_id=self.ADMIN_CHAT_ID)

    def incoming(self, raw_data):
        try:
            data = json.loads(raw_data)
            self.message = data['message']
            self.logger.info('incoming = \n%s' % json.dumps(data, indent=2))
            self.clear_cache()
            self.from_id = str(self.message['from']['id'])
            self.chat_id = str(self.message['chat']['id'])
            if 'text' in self.message:
                text = self.message['text']
                if text.startswith('/'):
                    for msg in self.execute_command(text):
                        self.send_message(msg)

            if not self.coder:
                url = settings.HTTPS_HOST_ + reverse('telegram:me')
                self.sendMessage(self.from_id, 'Follow on link %s to connect your account.' % url)
            else:
                if self.coder.settings.get('telegram', {}).get('unauthorized', False):
                    self.coder.settings.setdefault('telegram', {})['unauthorized'] = False
                    self.coder.save()
                History.objects.create(chat=self.group or self.chat, message=data).save()
        except Exception:
            if hasattr(self, 'from_id'):
                self.sendMessage(self.from_id, 'Thanks, but I do not know what I should do about it.')
            self.logger.error('Exception incoming message:\n%s\n%s' % (format_exc(), raw_data))
            try:
                self.sendMessage(
                    self.ADMIN_CHAT_ID,
                    'What need from me?',
                    reply_to_message_id=self.message['message_id'],
                )
            except Exception:
                pass

    def get_commands(self):
        return '\n'.join(
            '%s - %s' % (choice[1:], subparser.description)
            for s in self.parser._subparsers._actions
            if isinstance(s, argparse._SubParsersAction)
            for choice, subparser in list(s.choices.items())
        )

    def get_help(self):
        return '#Help @ClistBot\n\n' + '\n\n'.join(
            '##%s\n```\n#!text\n%s```' % (choice[1:], subparser.format_help())
            for s in self.parser._subparsers._actions
            if isinstance(s, argparse._SubParsersAction)
            for choice, subparser in list(s.choices.items())
        )

    def webhook(self):
        url = settings.HTTPS_HOST_ + reverse('telegram:incoming')
        self.logger.info('webhook url = %s' % url)
        return self.setWebhook(url)

    def unwebhook(self):
        self.logger.info('unwebhook')
        return self.setWebhook(None)
