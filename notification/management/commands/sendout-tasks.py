#!/usr/bin/env python
# -*- coding: utf-8 -*-

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from logging import getLogger
from notification.models import Task, Notification
from tg.bot import Bot
from telegram.error import Unauthorized
from traceback import format_exc
from django.urls import reverse


class Command(BaseCommand):
    help = 'Send out all unsent tasks'
    TELEGRAM_BOT = Bot()

    def handle(self, *args, **options):
        logger = getLogger('notification.sendout.tasks')
        qs = Task.unsent
        tasks = list(qs.all())
        qs.update(is_sent=True)

        for task in tasks:
            try:
                notification = task.notification
                coder = notification.coder
                if notification.method == Notification.TELEGRAM:
                    will_mail = False
                    if coder.chat and coder.chat.chat_id:
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
                        # FIXME: skipping, fixed on https://yandex.ru/support/mail-new/web/spam/honest-mailers.html
                        continue
                        send_mail(
                            settings.EMAIL_PREFIX_SUBJECT_ + task.subject,
                            '%s, connect telegram chat by link %s.' % (
                                coder.user.username,
                                settings.HTTPS_HOST_ + reverse('telegram:me')
                            ),
                            'Contest list <noreply@clist.by>',
                            [coder.user.email],
                            fail_silently=False,
                        )
                elif notification.method == Notification.EMAIL:
                    # FIXME: skipping, fixed on https://yandex.ru/support/mail-new/web/spam/honest-mailers.html
                    continue
                    send_mail(
                        settings.EMAIL_PREFIX_SUBJECT_ + task.subject,
                        task.addition['text'],
                        'Contest list <noreply@clist.by>',
                        [coder.user.email],
                        fail_silently=False,
                        html_message=task.message,
                    )
            except Exception:
                logger.error('Exception sendout task:\n%s' % format_exc())
                task.is_sent = False
                task.save()
