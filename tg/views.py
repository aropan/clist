from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect
from tg.models import Chat
from django.contrib.auth.models import User
from django.views.generic.base import View
from tg.bot import Bot


@login_required
def me(request):
    coder = request.user.coder
    url = 'https://telegram.me/ClistBot?start'

    chat = coder.chat
    if chat is None:
        chat = Chat.objects.create(coder=coder)
    if not chat.chat_id:
        chat.secret_key = User.objects.make_random_password(length=20)
        url += '=' + chat.secret_key
        chat.save()

    return HttpResponseRedirect(url)


class Incoming(View):

    def post(self, request):
        bot = Bot()
        try:
            bot.incoming(request.body)
        except Exception as e:
            bot.logger.critical(e)
        return HttpResponse('ok')
