from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.urls import reverse
from django.forms.models import model_to_dict
from django.contrib import auth
from django.contrib.auth.models import User
from my_oauth.models import Service, Token
from true_coders.models import Coder
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.conf import settings
from urllib.parse import parse_qsl

from datetime import timedelta
import string
import random
import requests
import json
import re


def generate_state(size=20, chars=string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


def query(request, name):
    redirect_url = request.GET.get('next', None)
    if redirect_url:
        request.session['next'] = redirect_url

    service = get_object_or_404(Service, name=name)
    args = model_to_dict(service)
    args['redirect_uri'] = request.build_absolute_uri(reverse('auth:response', args=(name, )))
    args['state'] = generate_state()
    request.session['state'] = args['state']
    url = re.sub('[\n\r]', '', service.code_uri % args)
    return redirect(url)


def process_data(request, service, access_token, response):
    if response.status_code != requests.codes.ok:
        raise Exception('Response status code not equal ok.')
    data = json.loads(response.text)
    data.update(access_token)
    for e in ('email', 'default_email', ):
        email = data.get(e, None)
        if email:
            break
    user_id = data.get(service.user_id_field, None)
    if not email or not user_id:
        raise Exception('Email or User ID not found.')
    token, created = Token.objects.get_or_create(
        service=service,
        user_id=user_id,
    )
    token.email = email
    token.data = data
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
    response = requests.get(service.data_uri % access_token)
    return process_data(request, service, access_token, response)


def response(request, name):
    service = get_object_or_404(Service, name=name)
    state = request.session.get(service.state_field, None)
    if state is None or state != request.GET['state']:
        return HttpResponseBadRequest()
    del request.session['state']
    args = model_to_dict(service)
    args.update(dict(list(request.GET.items())))
    args['redirect_uri'] = request.build_absolute_uri(reverse('auth:response', args=(name, )))
    if 'code' not in args:
        return HttpResponseForbidden()

    if service.token_post:
        post = json.loads(service.token_post % args)
        response = requests.post(service.token_uri, data=post)
    else:
        url = re.sub('[\n\r]', '', service.token_uri % args)
        response = requests.get(url)

    try:
        return process_access_token(request, service, response)
    except Exception as e:
        return HttpResponseBadRequest(e)


def login(request):
    redirect_url = request.GET.get('next', 'clist:main')
    if request.user.is_authenticated:
        return redirect(redirect_url)

    request.session['next'] = redirect_url
    return render(
        request,
        'login.html',
        {'services': Service.objects.all()},
    )


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
            if not username:
                context['error'] = 'Username can not be empty.'
            elif len(username) > 30:
                context['error'] = '30 characters or fewer.'
            elif not re.match(r'^[\-A-Za-z0-9_@\+\.]{1,30}$', username):
                context['error'] = 'Username may contain alphanumeric, _, @, +, . and - characters.'
            elif User.objects.filter(username=username).exists():
                q_token = q_token | Q(coder__user__username=username)
                context['error'] = 'User already exist.'
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

    return render(
        request,
        'signup.html',
        context,
    )


def logout(request):
    if request.user.is_authenticated:
        auth.logout(request)
    return redirect("/")
