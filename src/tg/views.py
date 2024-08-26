from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.views.generic.base import View

from tg.bot import Bot
from tg.models import Chat
from utils.strings import random_string


@login_required
def me(request):
    coder = request.user.coder
    url = f'https://telegram.me/{settings.TELEGRAM_NAME}?start'

    chat = coder.chat
    if chat is None:
        chat = Chat.objects.create(coder=coder)
    if not chat.chat_id:
        chat.secret_key = random_string(length=20)
        url += '=' + chat.secret_key
        chat.save()

    return HttpResponseRedirect(url)


@login_required
def unlink(request):
    coder = request.user.coder
    coder.chat.delete()
    return HttpResponseRedirect(reverse('coder:settings', kwargs=dict(tab='social')))


class Incoming(View):

    def post(self, request):
        bot = Bot()
        try:
            bot.incoming(request.body)
        except Exception as e:
            bot.logger.critical(e)
        return HttpResponse('ok')
