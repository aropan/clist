#!/usr/bin/env python
# -*- coding: utf-8 -*-

from traceback import format_exc
from logging import getLogger
from datetime import timedelta
from copy import deepcopy

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

from notification.models import Task, Notification
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

    def get_message(self, task):
        if 'contests' in task.addition:
            notify = task.notification
            contests = Contest.objects.filter(pk__in=task.addition['contests'])
            context = deepcopy(task.addition.get('context', {}))
            context.update({
                'contests': contests,
                'notification': notify,
                'coder': notify.coder,
                'domain': settings.HTTPS_HOST_,
            })
            subject = render_to_string('subject', context).strip()
            context['subject'] = subject
            method = notify.method.split(':', 1)[0]
            message = render_to_string('message/%s' % method, context).strip()
        else:
            subject = ''
            message = ''
            context = {}

        if task.subject:
            subject = task.subject + subject

        if task.message:
            message = task.message + message

        return subject, message, context

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
        for task in tqdm.tqdm(qs.iterator(), 'sending'):
            try:
                task.is_sent = True
                notification = task.notification
                coder = notification.coder
                method, *args = notification.method.split(':', 1)
                message = self.get_message(task)
                subject, message, context = self.get_message(task)
                if method == Notification.TELEGRAM:
                    if args:
                        self.TELEGRAM_BOT.send_message(message, args[0], reply_markup=False)
                    elif coder.chat and coder.chat.chat_id:
                        try:
                            if not coder.settings.get('telegram', {}).get('unauthorized', False):
                                self.TELEGRAM_BOT.send_message(message, coder.chat.chat_id, reply_markup=False)
                        except Unauthorized:
                            coder.settings.setdefault('telegram', {})['unauthorized'] = True
                            coder.save()
                elif method == Notification.EMAIL:
                    send_mail(
                        subject,
                        message,
                        'CLIST <noreply@clist.by>',
                        [coder.user.email],
                        fail_silently=False,
                        html_message=message,
                    )
                elif method == Notification.WEBBROWSER:
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
            except Exception:
                logger.error('Exception sendout task:\n%s' % format_exc())
                task.is_sent = False
            if task.is_sent:
                done += 1
            else:
                failed += 1
            task.save()
        logger.info(f'Done: {done}, failed: {failed}')
