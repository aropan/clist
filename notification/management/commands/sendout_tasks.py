#!/usr/bin/env python
# -*- coding: utf-8 -*-

from traceback import format_exc
from logging import getLogger
from datetime import timedelta
from copy import deepcopy
from smtplib import SMTPResponseException

import tqdm
from django.core.mail import send_mail
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Prefetch
from django_print_sql import print_sql_decorator
from django.utils.timezone import now
from django.template.loader import render_to_string
from webpush import send_user_notification

from notification.models import Task
from telegram.error import Unauthorized
from clist.models import Contest
from tg.bot import Bot
from tg.models import Chat


class Command(BaseCommand):
    help = 'Send out all unsent tasks'
    TELEGRAM_BOT = Bot()

    def add_arguments(self, parser):
        parser.add_argument('--coders', nargs='+')
        parser.add_argument('--dryrun', action='store_true', default=False)

    def get_message(self, method, data, **kwargs):
        subject_ = kwargs.pop('subject', None)
        message_ = kwargs.pop('message', None)

        if 'contests' in data:
            contests = Contest.objects.filter(pk__in=data['contests'])
            context = deepcopy(data.get('context', {}))
            context.update({
                'contests': contests,
                'domain': settings.HTTPS_HOST_,
            })
            context.update(kwargs)
            subject = render_to_string('subject', context).strip()
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
        if method == settings.NOTIFICATION_CONF.TELEGRAM:
            if args:
                self.TELEGRAM_BOT.send_message(message, args[0], reply_markup=False)
            elif coder.chat and coder.chat.chat_id:
                try:
                    if not coder.settings.get('telegram', {}).get('unauthorized', False):
                        self.TELEGRAM_BOT.send_message(message, coder.chat.chat_id, reply_markup=False)
                except Unauthorized:
                    coder.settings.setdefault('telegram', {})['unauthorized'] = True
                    coder.save()
        elif method == settings.NOTIFICATION_CONF.EMAIL:
            send_mail(
                subject,
                message,
                'CLIST <noreply@clist.by>',
                [coder.user.email],
                fail_silently=False,
                html_message=message,
            )
        elif method == settings.NOTIFICATION_CONF.WEBBROWSER:
            payload = {
                'head': subject,
                'body': message,
            }
            contests = list(context.get('contests', []))
            if len(contests) == 1:
                contest = contests[0]
                payload['url'] = contest.url
                payload['icon'] = f'{settings.HTTPS_HOST_}/imagefit/static_resize/64x64/{contest.resource.icon}'

            send_user_notification(
                user=coder.user,
                payload=payload,
                ttl=300,
            )

    @print_sql_decorator()
    @transaction.atomic
    def handle(self, *args, **options):
        coders = options.get('coders')
        dryrun = options.get('dryrun')

        logger = getLogger('notification.sendout.tasks')

        delete_info = Task.objects.filter(is_sent=True, modified__lte=now() - timedelta(days=31)).delete()
        logger.info(f'Tasks cleared: {delete_info}')

        if dryrun:
            qs = Task.objects.all()
        else:
            qs = Task.unsent.all()
        qs = qs.select_related('notification__coder')
        qs = qs.prefetch_related(
            Prefetch(
                'notification__coder__chat_set',
                queryset=Chat.objects.filter(is_group=False),
                to_attr='cchat',
            )
        )
        if coders:
            qs = qs.filter(notification__coder__username__in=coders)

        if dryrun:
            qs = qs.order_by('-modified')[:1]

        done = 0
        failed = 0
        stop_email = False
        for task in tqdm.tqdm(qs.iterator(), 'sending'):
            if stop_email and task.notification.method == settings.NOTIFICATION_CONF.EMAIL:
                continue

            try:
                task.is_sent = True
                notification = task.notification
                coder = notification.coder
                method = notification.method

                self.send_message(
                    coder,
                    method,
                    task.addition,
                    subject=task.subject,
                    message=task.message,
                    notification=notification,
                )
            except Exception as e:
                logger.error('Exception sendout task:\n%s' % format_exc())
                task.is_sent = False
                if isinstance(e, SMTPResponseException):
                    stop_email = True
            if task.is_sent:
                done += 1
            else:
                failed += 1
            task.save()
        logger.info(f'Done: {done}, failed: {failed}')
