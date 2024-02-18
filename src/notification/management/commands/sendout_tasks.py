#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
from copy import deepcopy
from datetime import timedelta
from logging import getLogger
from smtplib import SMTPDataError, SMTPResponseException
from time import sleep

import tqdm
import yaml
from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend
from django.core.mail.message import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.db.models import Prefetch, Q
from django.template.loader import render_to_string
from django.utils.timezone import now
from django_print_sql import print_sql_decorator
from filelock import FileLock
from requests.exceptions import ConnectionError
from telegram.error import ChatMigrated, Unauthorized
from webpush import send_user_notification
from webpush.utils import WebPushException

from clist.models import Contest
from notification.models import Task
from tg.bot import Bot
from tg.models import Chat
from utils.traceback_with_vars import colored_format_exc

logger = getLogger('notification.sendout.tasks')


class Command(BaseCommand):
    help = 'Send out all unsent tasks'
    TELEGRAM_BOT = Bot()
    CONFIG_FILE = __file__ + '.yaml'
    N_STOP_EMAIL_FAILED_LIMIT = 5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.email_connection = None
        self.n_messages_sent = 0
        self.config = None

    def add_arguments(self, parser):
        parser.add_argument('--dryrun', action='store_true', default=False)
        parser.add_argument('--force', action='store_true', default=False)
        parser.add_argument('--coders', nargs='+')

    def get_message(self, method, data, **kwargs):
        subject_ = kwargs.pop('subject', None)
        message_ = kwargs.pop('message', None)

        if 'contests' in data:
            contests = Contest.objects.filter(pk__in=data['contests'])
            context = deepcopy(data.get('context', {}))
            context.update({
                'contests': contests,
                'domain': settings.MAIN_HOST_URL_,
            })
            context.update(kwargs)
            subject = render_to_string('subject', context).strip()
            subject = re.sub(r'\s+', ' ', subject)
            context['subject'] = subject
            method = method.split(':', 1)[0]
            message = render_to_string('message/%s' % method, context).strip()
        else:
            subject = ''
            message = ''
            context = {}

        if subject_:
            subject = subject_ + subject

        if message_:
            message = message_ + message

        return subject, message, context

    def send_message(self, coder, method, data, **kwargs):
        method, *args = method.split(':', 1)
        subject, message, context = self.get_message(method=method, data=data, coder=coder,  **kwargs)
        if not message:
            return
        response = None

        def delete_notification(msg):
            if 'notification' in kwargs:
                if 'task' in kwargs and kwargs['task'].created + timedelta(minutes=30) > now():
                    return False
                delete_info = kwargs['notification'].delete()
                logger.error(f'{msg}, delete info = {delete_info}')
                return True
            return False

        if method == settings.NOTIFICATION_CONF.TELEGRAM:
            if args:
                try:
                    response = self.TELEGRAM_BOT.send_message(message, args[0], reply_markup=False)
                    response = response.to_dict()
                except Unauthorized as e:
                    if 'bot was kicked from' in str(e) and delete_notification(e):
                        return 'removed'
                except ChatMigrated as e:
                    new_chat_id = str(e).strip().split()[-1]
                    notification = kwargs['notification']
                    notification.method = f'telegram:{new_chat_id}'
                    notification.save()
            elif coder.chat and coder.chat.chat_id:
                try:
                    if not coder.settings.get('telegram', {}).get('unauthorized', False):
                        response = self.TELEGRAM_BOT.send_message(message, coder.chat.chat_id, reply_markup=False)
                        response = response.to_dict()
                except Unauthorized as e:
                    if 'bot was blocked by the user' in str(e):
                        coder.chat.delete()
                    else:
                        coder.settings.setdefault('telegram', {})['unauthorized'] = True
                        coder.save()
            elif delete_notification('Strange notification'):
                return 'removed'
        elif method == settings.NOTIFICATION_CONF.EMAIL:
            if self.n_messages_sent % 20 == 0:
                if self.n_messages_sent:
                    sleep(10)
                self.email_connection = EmailBackend()
            mail = EmailMultiAlternatives(
                subject=subject,
                body=message,
                from_email='CLIST <noreply@clist.by>',
                to=[coder.user.email],
                bcc=['noreply@clist.by'],
                connection=self.email_connection,
                alternatives=[(message, 'text/html')],
            )
            mail.send()
            self.n_messages_sent += 1
            sleep(2)
        elif method == settings.NOTIFICATION_CONF.WEBBROWSER:
            payload = {
                'head': subject,
                'body': message,
            }
            contests = list(context.get('contests', []))
            if len(contests) == 1:
                contest = contests[0]
                payload['url'] = contest.url
                payload['icon'] = f'{settings.HTTPS_HOST_URL_}/media/sizes/64x64/{contest.resource.icon}'

            try:
                send_user_notification(
                    user=coder.user,
                    payload=payload,
                    ttl=300,
                )
            except WebPushException as e:
                if '403 Forbidden' in str(e) and delete_notification(e):
                    return 'removed'
            except ConnectionError as e:
                if 'Max retries exceeded with url' in str(e) and delete_notification(e):
                    return 'removed'

        task = kwargs.get('task')
        if task is not None and response:
            task.response = response
            task.save()

    def load_config(self):
        if os.path.exists(self.CONFIG_FILE):
            with open(self.CONFIG_FILE, 'r') as fo:
                self.config = yaml.safe_load(fo)
        else:
            self.config = {}
        self.config.setdefault('stop_email', {})
        self.config['stop_email'].setdefault('n_failed', 0)

    def save_config(self):
        lock = FileLock(self.CONFIG_FILE)
        with lock.acquire(timeout=60):
            with open(self.CONFIG_FILE, 'w') as fo:
                yaml.dump(self.config, fo, indent=2)

    @print_sql_decorator()
    def handle(self, *args, **options):
        self.load_config()
        dryrun = options.get('dryrun')
        coders = options.get('coders')

        stop_email = settings.STOP_EMAIL_ and not dryrun
        if (
            self.config['stop_email']['n_failed'] >= self.N_STOP_EMAIL_FAILED_LIMIT
            and now() - self.config['stop_email']['failed_time'] < timedelta(hours=2)
        ):
            stop_email = True
        clear_email_task = False

        delete_info = Task.objects.filter(
            Q(is_sent=True, modified__lte=now() - timedelta(days=1)) |
            Q(created__lte=now() - timedelta(days=2))
        ).delete()
        logger.info(f'Tasks cleared: {delete_info}')

        qs = Task.objects.all() if coders and options.get('force') else Task.unsent.all()
        if coders:
            qs = qs.filter(periodical_notification__coder__username__in=coders)
        qs = qs.prefetch_related(
            Prefetch(
                'notification__coder__chat_set',
                queryset=Chat.objects.filter(is_group=False),
                to_attr='cchat',
            )
        )
        qs = qs.order_by('modified')

        done = 0
        failed = 0
        deleted = 0
        for is_email_iteration in range(2):
            for task in tqdm.tqdm(qs, 'sending'):
                is_email = task.notification.method == settings.NOTIFICATION_CONF.EMAIL
                if is_email_iteration != is_email:
                    continue

                if stop_email and is_email:
                    if clear_email_task:
                        contests = task.addition.get('contests', [])
                        if contests and not Contest.objects.filter(pk__in=contests, start_time__gt=now()).exists():
                            task.delete()
                            deleted += 1
                    continue

                try:
                    notification = task.notification
                    coder = notification.coder
                    method = notification.method

                    status = self.send_message(
                        coder,
                        method,
                        task.addition,
                        subject=task.subject,
                        message=task.message,
                        task=task,
                        notification=notification,
                    )
                    if status == 'removed':
                        continue

                    task.is_sent = True
                    task.save()
                except Exception as e:
                    logger.debug(colored_format_exc())
                    logger.warning(f'task = {task}')
                    logger.error(f'Exception sendout task: {e}')
                    task.is_sent = False
                    task.save()
                    if isinstance(e, (SMTPResponseException, SMTPDataError)):
                        stop_email = True

                        if self.n_messages_sent:
                            self.config['stop_email']['n_failed'] = 1
                        else:
                            self.config['stop_email']['n_failed'] += 1
                        if self.config['stop_email']['n_failed'] >= self.N_STOP_EMAIL_FAILED_LIMIT:
                            clear_email_task = True

                        self.config['stop_email']['failed_time'] = now()

                if task.is_sent:
                    done += 1
                else:
                    failed += 1
        logger.info(f'Done: {done}, failed: {failed}, deleted: {deleted}')
        self.save_config()
