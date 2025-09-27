from django.conf import settings
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from clist.templatetags.extras import is_yes
from pyclist.middleware import RedirectException
from ranking.models import Account, Coder
from true_coders.models import CoderList


def add_query_to_list(request, uuid, query):
    if not request.user.is_authenticated or not uuid or not query:
        return
    coder = request.user.coder
    get_object_or_404(CoderList, owner=coder, uuid=uuid)
    url = reverse('coder:list', args=(uuid,))
    request.session['view_list_request_post'] = {'raw': query, 'uuid': uuid}
    raise RedirectException(redirect(url))


def add_query_to_chat(request, chat_id, profiles):
    if not request.user.is_authenticated or not chat_id or not profiles:
        return
    coder = request.user.coder
    chat = get_object_or_404(coder.chat_set, chat_id=chat_id)
    for profile in profiles:
        if isinstance(profile, Coder):
            if chat.coders.filter(pk=profile.pk).exists():
                request.logger.warning(f"Coder {profile.display_name} already in chat {chat}")
            else:
                chat.coders.add(profile)
                request.logger.info(f"Added coder {profile.display_name} to chat {chat}")
        elif isinstance(profile, Account):
            if chat.accounts.filter(pk=profile.pk).exists():
                request.logger.warning(f"Account {profile.display()} already in chat {chat}")
            else:
                chat.accounts.add(profile)
                request.logger.info(f"Added account {profile.display()} to chat {chat}")
        else:
            request.logger.error(f"Unknown profile type: {type(profile)} for chat {chat}")


def get_or_set_upsolving_filter(request, field='upsolving'):
    upsolving_filter = request.get_filtered_value(field)

    if request.user.is_authenticated:
        coder = request.user.coder
        if upsolving_filter:
            coder.settings['upsolving_filter'] = upsolving_filter
            coder.save(update_fields=['settings'])
        else:
            upsolving_filter = coder.settings.get('upsolving_filter')
    else:
        session = request.session
        if upsolving_filter:
            session['upsolving_filter'] = upsolving_filter
        else:
            upsolving_filter = session.get('upsolving_filter')

    if upsolving_filter is None:
        upsolving_filter = settings.UPSOLVING_FILTER_DEFAULT
    else:
        upsolving_filter = is_yes(upsolving_filter)

    return upsolving_filter
