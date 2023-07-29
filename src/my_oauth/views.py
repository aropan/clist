
import json
import random
import re
import string
from copy import deepcopy
from datetime import timedelta
from io import StringIO
from urllib.parse import parse_qsl

import requests
from django.conf import settings
from django.contrib import auth, messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import User
from django.core.management.commands import dumpdata
from django.db import transaction
from django.db.models import Count, Q
from django.forms.models import model_to_dict
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from flatten_dict import flatten

from clist.templatetags.extras import relative_url
from my_oauth.models import Service, Token
from true_coders.models import Coder


def generate_state(size=20, chars=string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


def query(request, name):
    redirect_url = request.GET.get('next', None)
    if redirect_url:
        request.session['next'] = redirect_url

    service = get_object_or_404(Service.objects, name=name)
    args = model_to_dict(service)
    args['redirect_uri'] = settings.HTTPS_HOST_ + reverse('auth:response', args=(name, ))
    args['state'] = generate_state()
    request.session['state'] = args['state']
    url = re.sub('[\n\r]', '', service.code_uri % args)
    return redirect(url)


@login_required
def unlink(request, name):
    coder = request.user.coder
    if coder.token_set.count() < 2:
        messages.error(request, 'Not enough services')
    else:
        coder.token_set.filter(service__name=name).delete()
    return HttpResponseRedirect(reverse('coder:settings', kwargs=dict(tab='social')))


def process_data(request, service, access_token, data):
    d = deepcopy(data)
    d.update(access_token)
    d = flatten(d, reducer='underscore')

    email = d.get(service.email_field, None)
    user_id = d.get(service.user_id_field, None)
    if not email or not user_id:
        raise Exception('Email or User ID not found.')

    token, created = Token.objects.get_or_create(service=service, user_id=user_id)
    token.access_token = access_token
    token.data = data
    token.email = email
    token.save()

    request.session['token_id'] = token.id
    return redirect('auth:signup')


def process_access_token(request, service, response):
    if response.status_code != requests.codes.ok:
        raise Exception('Response status code not equal ok.')
    try:
        access_token = json.loads(response.text)
    except Exception:
        access_token = dict(parse_qsl(response.text))

    if service.data_header:
        args = model_to_dict(service)
        args.update(access_token)
        headers = json.loads(service.data_header % args)
    else:
        headers = None

    data = {}
    for data_uri in service.data_uri.split():
        url = data_uri % access_token
        response = requests.get(url, headers=headers)

        if response.status_code != requests.codes.ok:
            raise Exception('Response status code not equal ok.')

        response = json.loads(response.text)
        while isinstance(response, list) or isinstance(response, dict) and len(response) == 1:
            array = response if isinstance(response, list) else list(response.values())
            response = array[0]
            for d in array[1:]:
                if not isinstance(response, dict):
                    break
                if not isinstance(d, dict):
                    continue
                if d.get('primary') and not response.get('primary'):
                    response = d

        data.update(response)

    return process_data(request, service, access_token, data)


def response(request, name):
    service = get_object_or_404(Service.objects, name=name)
    state = request.session.get(service.state_field, None)
    try:
        if state is None or state != request.GET.get('state'):
            raise KeyError('Not found state')
        del request.session['state']
        args = model_to_dict(service)
        get_args = list(request.GET.items())
        args.update(dict(get_args))
        args['redirect_uri'] = settings.HTTPS_HOST_ + reverse('auth:response', args=(name, ))
        if 'code' not in args:
            raise ValueError(f'Not found code. Received {get_args}')

        if service.token_post:
            post = json.loads(service.token_post % args)
            response = requests.post(service.token_uri, data=post)
        else:
            url = re.sub('[\n\r]', '', service.token_uri % args)
            response = requests.get(url)
        return process_access_token(request, service, response)
    except Exception as e:
        messages.error(request, "ERROR: {}".format(str(e).strip("'")))
        return signup(request)


def login(request):
    redirect_url = request.GET.get('next')
    if not redirect_url or not redirect_url.startswith('/'):
        redirect_url = relative_url(request.META.get('HTTP_REFERER')) or 'clist:main'
    if request.user.is_authenticated:
        return redirect(redirect_url)

    services = Service.active_objects.annotate(n_tokens=Count('token')).order_by('-n_tokens')
    if not services:
        action = request.POST.get('action')
        username = request.POST.get('username')
        password = request.POST.get('password')
        if action == 'login':
            user = auth.authenticate(request, username=username, password=password)
            if user is None:
                return HttpResponseBadRequest('Authentication failed')
            auth.login(request, user)
            return redirect(redirect_url)

    request.session['next'] = redirect_url
    return render(
        request,
        'login.html',
        {'services': services},
    )


USERNAME_EMPTY_ERROR = 'Username can not be empty.'
USERNAME_LONG_ERROR = '30 characters or fewer.'
USERNAME_WRONG_ERROR = 'Username may contain alphanumeric, _, @, +, . and - characters.'
USERNAME_EXIST_ERROR = 'User already exist.'


def username_error(username):
    if not username:
        return USERNAME_EMPTY_ERROR
    elif len(username) > 30:
        return USERNAME_LONG_ERROR
    elif not re.match(r'^[\-A-Za-z0-9_@\+\.]{1,30}$', username):
        return USERNAME_WRONG_ERROR
    elif User.objects.filter(username__iexact=username).exists():
        return USERNAME_EXIST_ERROR
    return False


def signup(request, action=None):
    context = {}
    token_id = request.session.pop('token_id', None)
    if token_id:
        try:
            token = Token.objects.get(id=token_id)
        except Token.DoesNotExist:
            return signup(request)

        user = None
        coder = token.coder
        if coder:
            user = coder.user
        else:
            t = Token.objects.filter(email=token.email, coder__isnull=False).filter(~Q(id=token_id)).first()
            if t:
                user = t.coder.user
                token.coder = user.coder
                token.save()
        if user and user.is_active:
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            auth.login(request, user)
            return signup(request)

        if request.user.is_authenticated:
            token.coder = request.user.coder
            token.save()
            return signup(request)

        request.session['token_id'] = token_id

        q_token = Q(email=token.email)

        if request.POST and 'signup' in request.POST:
            username = request.POST.get('username', None)
            error = username_error(username)
            if error:
                context['error'] = error
                if error == USERNAME_EXIST_ERROR:
                    q_token = q_token | Q(coder__user__username__iexact=username)
            else:
                with transaction.atomic():
                    user = User.objects.create_user(username, token.email)
                    token.coder = Coder.objects.create(user=user)
                    token.save()
                return signup(request)

        tokens = Token.objects.filter(q_token).filter(~Q(id=token_id))
        context['tokens'] = tokens

        if tokens.count():
            if token.n_viewed_tokens >= settings.LIMIT_N_TOKENS_VIEW:
                now = timezone.now()
                if token.tokens_view_time is None:
                    token.tokens_view_time = now
                if token.tokens_view_time + timedelta(hours=settings.LIMIT_TOKENS_VIEW_WAIT_IN_HOURS) < now:
                    token.n_viewed_tokens = 0
                    token.tokens_view_time = None
                else:
                    context['limit_tokens_view'] = True
            token.n_viewed_tokens += 1
            token.save()

        context['token'] = token
    else:
        if request.user.is_authenticated:
            return redirect(request.session.pop('next', 'clist:main'))
        return redirect('auth:login')

    return render(request, 'signup.html', context)


def logout(request):
    if request.user.is_authenticated:
        auth.logout(request)
    return redirect("/")


@permission_required('my_oauth.view_services_dump_data')
def services_dumpdata(request):
    out = StringIO()
    dumpdata.Command(stdout=out).run_from_argv([
        'manage.py',
        'dumpdata',
        'my_oauth.service',
        '--format', 'json'
    ])
    services = json.loads(out.getvalue())
    for service in services:
        service['fields']['secret'] = None
        service['fields']['app_id'] = None
    return HttpResponse(json.dumps(services), content_type="application/json")
