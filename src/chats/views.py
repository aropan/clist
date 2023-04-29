from django.shortcuts import render
from el_pagination.decorators import page_template

from chats.models import ExternalChat
from clist.models import Contest, Resource
from pyclist.decorators import context_pagination


def index(request):
    return render(request, 'chat.html')


@page_template('chats_paging.html')
@context_pagination()
def chats(request, template='chats.html'):
    chats = ExternalChat.objects.all()

    resources = [r for r in request.GET.getlist('resource') if r]
    if resources:
        resources = list(Resource.objects.filter(pk__in=resources))

    contests = [r for r in request.GET.getlist('contest') if r]
    if contests:
        contests = list(Contest.objects.filter(pk__in=contests))

    chat_type_select = {
        'noajax': True,
        'nomultiply': True,
        'nourl': True,
        'nogroupby': True,
        'required': True,
        'options': dict((k, v)
                        for k, v in ExternalChat.ExternalChatType.choices
                        if k != ExternalChat.ExternalChatType.BLANK),
        'values': [r for r in request.GET.getlist('app') if r],
    }

    context = {
        'chat_type_select': chat_type_select,
        'chats': chats,
        'params': {
            'resources': resources,
            'contests': contests,
        },
    }
    return template, context
