#!/usr/bin/env python
# -*- coding: utf-8 -*-

from traceback import format_exc
from logging import getLogger
from datetime import timedelta

import tqdm
# from django.conf import settings
# from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Prefetch
from django_print_sql import print_sql_decorator
from django.utils.timezone import now
# from django.urls import reverse
from notification.models import Task, Notification
from telegram.error import Unauthorized

from tg.bot import Bot
from tg.models import Chat


class Command(BaseCommand):
    help = 'Send out all unsent tasks'
    TELEGRAM_BOT = Bot()

    @print_sql_decorator()
    @transaction.atomic
    def handle(self, *args, **options):
        logger = getLogger('notification.sendout.tasks')

        delete_info = Task.objects.filter(is_sent=True, modified__lte=now() - timedelta(days=31)).delete()
        logger.info(f'Tasks cleared: {delete_info}')

        qs = Task.unsent.all()
        qs = qs.select_related('notification__coder')
        qs = qs.prefetch_related(
            Prefetch(
                'notification__coder__chat_set',
                queryset=Chat.objects.filter(is_group=False),
                to_attr='cchat',
            )
        )

        done = 0
        failed = 0
        for task in tqdm.tqdm(qs.iterator(), 'sending'):
            try:
                task.is_sent = True
                notification = task.notification
                coder = notification.coder
                method, *args = notification.method.split(':', 1)
                if method == Notification.TELEGRAM:
                    will_mail = False

                    if args:
                        self.TELEGRAM_BOT.send_message(task.message, args[0])
                    elif coder.chat and coder.chat.chat_id:
                        try:
                            if not coder.settings.get('telegram', {}).get('unauthorized', False):
                                self.TELEGRAM_BOT.send_message(task.message, coder.chat.chat_id)
                        except Unauthorized:
                            coder.settings.setdefault('telegram', {})['unauthorized'] = True
                            coder.save()
                            will_mail = True
                    else:
                        will_mail = True

                    if will_mail:
                        pass
                        # FIXME: skipping, fixed on https://yandex.ru/support/mail-new/web/spam/honest-mailers.html
                        # send_mail(
                        #     settings.EMAIL_PREFIX_SUBJECT_ + task.subject,
                        #     '%s, connect telegram chat by link %s.' % (
                        #         coder.user.username,
                        #         settings.HTTPS_HOST_ + reverse('telegram:me')
                        #     ),
                        #     'Contest list <noreply@clist.by>',
                        #     [coder.user.email],
                        #     fail_silently=False,
                        # )
                elif method == Notification.EMAIL:
                    pass
                    # FIXME: skipping, fixed on https://yandex.ru/support/mail-new/web/spam/honest-mailers.html
                    # send_mail(
                    #     settings.EMAIL_PREFIX_SUBJECT_ + task.subject,
                    #     task.addition['text'],
                    #     'Contest list <noreply@clist.by>',
                    #     [coder.user.email],
                    #     fail_silently=False,
                    #     html_message=task.message,
                    # )
            except Exception:
                logger.error('Exception sendout task:\n%s' % format_exc())
                task.is_sent = False
            if task.is_sent:
                done += 1
            else:
                failed += 1
            task.save()
        logger.info(f'Done: {done}, failed: {failed}')
