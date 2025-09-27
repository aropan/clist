import json
import random
import re
import string
from copy import deepcopy
from datetime import timedelta
from io import StringIO
from urllib.parse import quote

import requests
from django.conf import settings
from django.contrib import auth, messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import User
from django.core.management.commands import dumpdata
from django.db import transaction
from django.db.models import Count, Q
from django.forms.models import model_to_dict
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from flatten_dict import flatten

from clist.templatetags.extras import allowed_redirect
from my_oauth.models import Credential, Form, Service, Token
from my_oauth.utils import access_token_from_response, refresh_acccess_token
from true_coders.models import Coder


def generate_state(size=20, chars=string.ascii_uppercase + string.digits):
    return "".join(random.choice(chars) for _ in range(size))


def query(request, name):
    service = get_object_or_404(Service.objects, name=name)
    args = model_to_dict(service)
    args["redirect_uri"] = settings.HTTPS_HOST_URL_ + reverse("auth:response", args=(name,))
    args["state"] = generate_state()
    if service.code_args:
        args.update(json.loads(service.code_args % args))
    if code_args := request.session.pop("token_code_args", None):
        args.update(json.loads(code_args % args))
    request.session["state"] = args["state"]
    url = re.sub("[\n\r]", "", service.code_uri % args)
    return redirect(url)


@login_required
def unlink(request, name):
    coder = request.user.coder
    if coder.token_set.count() < 2:
        messages.error(request, "Not enough services")
    else:
        coder.token_set.filter(service__name=name).delete()
    return allowed_redirect(reverse("coder:settings", kwargs={"tab": "social"}))


@login_required
def refresh(request, name):
    token = get_object_or_404(
        request.user.coder.token_set,
        service__name=name,
        service__refresh_token_uri__isnull=False,
    )
    access_token = refresh_acccess_token(token)
    request.session["token_url"] = reverse("coder:settings", kwargs={"tab": "social"})
    ret = process_access_token(request, token.service, access_token)
    request.logger.success(f"{token.service.title} token refreshed")
    return ret


def process_data(request, service, access_token, data):
    d = deepcopy(data)
    d.update(access_token)
    d = flatten(d, reducer="underscore")

    user_id = d.get(service.user_id_field, None)
    email = d.get(service.email_field, None)
    redirect_url = request.session.pop("token_url", None)
    if not user_id:
        raise Exception("User ID not found.")
    if not email and not redirect_url:
        raise Exception("Email not found.")

    token, _ = Token.objects.get_or_create(service=service, user_id=user_id)
    token.access_token = access_token
    token.data = data
    token.email = email
    token.update_expires_at(d.get("expires_in"))
    token.save()

    if redirect_url:
        if token_id_field := request.session.pop("token_id_field", None):
            request.session[token_id_field] = token.id
        if token_timestamp_field := request.session.pop("token_timestamp_field", None):
            request.session[token_timestamp_field] = timezone.now().timestamp()
        return allowed_redirect(redirect_url)

    request.session["token_id"] = token.id
    return redirect("auth:signup")


def process_access_token(request, service, access_token):
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
            raise Exception("Response status code not equal ok.")

        response = json.loads(response.text)
        while isinstance(response, list) or isinstance(response, dict) and len(response) == 1:
            array = response if isinstance(response, list) else list(response.values())
            response = array[0]
            for d in array[1:]:
                if not isinstance(response, dict):
                    break
                if not isinstance(d, dict):
                    continue
                if d.get("primary") and not response.get("primary"):
                    response = d

        data.update(response)

    return process_data(request, service, access_token, data)


def response(request, name):
    service = get_object_or_404(Service.objects, name=name)
    state = request.session.get(service.state_field, None)
    try:
        if state is None or state != request.GET.get("state"):
            raise KeyError("Not found state")
        del request.session["state"]
        args = model_to_dict(service)
        get_args = list(request.GET.items())
        args.update(dict(get_args))
        args["redirect_uri"] = settings.HTTPS_HOST_URL_ + reverse("auth:response", args=(name,))
        if "code" not in args:
            raise ValueError(f"Not found code. Received {get_args}")

        if service.token_post:
            post = json.loads(service.token_post % args)
            response = requests.post(service.token_uri, data=post)
        else:
            url = re.sub("[\n\r]", "", service.token_uri % args)
            response = requests.get(url)
        access_token = access_token_from_response(response)
        return process_access_token(request, service, access_token)
    except Exception as e:
        messages.error(request, "ERROR: {}".format(str(e).strip("'")))
        return signup(request)


def login(request):
    request.session.pop("token_url", None)

    redirect_url = request.GET.get("next")
    if request.user.is_authenticated:
        return allowed_redirect(redirect_url)

    session_durations = settings.SESSION_DURATIONS_
    session_duration = request.POST.get("session_duration")
    if session_duration in session_durations:
        request.session.set_expiry(session_durations[session_duration]["value"])

    services = Service.active_objects.annotate(n_tokens=Count("token")).order_by("-n_tokens")
    if not services:
        action = request.POST.get("action")
        username = request.POST.get("username")
        password = request.POST.get("password")
        if action == "login":
            user = auth.authenticate(request, username=username, password=password)
            if user is None:
                return HttpResponseBadRequest("Authentication failed")
            auth.login(request, user)
            return allowed_redirect(redirect_url)

    request.session["next"] = redirect_url
    service = request.POST.get("service")
    if service:
        return query(request, service)

    return render(
        request,
        "login.html",
        {
            "services": services,
            "session_durations": session_durations,
        },
    )


USERNAME_EMPTY_ERROR = "Username can not be empty."
USERNAME_LONG_ERROR = "30 characters or fewer."
USERNAME_WRONG_ERROR = "Username may contain alphanumeric, _, @, +, . and - characters."
USERNAME_EXIST_ERROR = "User already exist."


def username_error(username):
    if not username:
        return USERNAME_EMPTY_ERROR
    elif len(username) > 30:
        return USERNAME_LONG_ERROR
    elif not re.match(r"^[\-A-Za-z0-9_@\+\.]{1,30}$", username):
        return USERNAME_WRONG_ERROR
    elif User.objects.filter(username__iexact=username).exists():
        return USERNAME_EXIST_ERROR
    return False


def signup(request, action=None):
    context = {}
    token_id = request.session.pop("token_id", None)
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
            user.backend = "django.contrib.auth.backends.ModelBackend"
            auth.login(request, user)
            return signup(request)

        if request.user.is_authenticated:
            token.coder = request.user.coder
            token.save()
            return signup(request)

        request.session["token_id"] = token_id

        q_token = Q(email=token.email)

        if request.POST and "signup" in request.POST:
            username = request.POST.get("username", None)
            error = username_error(username)
            if error:
                context["error"] = error
                if error == USERNAME_EXIST_ERROR:
                    q_token = q_token | Q(coder__user__username__iexact=username)
            else:
                with transaction.atomic():
                    user = User.objects.create_user(username, token.email)
                    token.coder = Coder.objects.create(user=user)
                    token.save()
                return signup(request)

        tokens = Token.objects.filter(q_token).filter(~Q(id=token_id))
        context["tokens"] = tokens

        if tokens.count():
            if token.n_viewed_tokens >= settings.LIMIT_N_TOKENS_VIEW:
                now = timezone.now()
                if token.tokens_view_time is None:
                    token.tokens_view_time = now
                if token.tokens_view_time + timedelta(hours=settings.LIMIT_TOKENS_VIEW_WAIT_IN_HOURS) < now:
                    token.n_viewed_tokens = 0
                    token.tokens_view_time = None
                else:
                    context["limit_tokens_view"] = True
            token.n_viewed_tokens += 1
            token.save()

        context["token"] = token
    else:
        if request.user.is_authenticated:
            return allowed_redirect(request.session.pop("next", reverse("clist:main")))
        return redirect("auth:login")

    return render(request, "signup.html", context)


def logout(request):
    if request.user.is_authenticated:
        auth.logout(request)
    return redirect("/")


@permission_required("my_oauth.view_services_dump_data")
def services_dumpdata(request):
    out = StringIO()
    dumpdata.Command(stdout=out).run_from_argv(["manage.py", "dumpdata", "my_oauth.service", "--format", "json"])
    services = json.loads(out.getvalue())
    for service in services:
        service["fields"]["secret"] = None
        service["fields"]["app_id"] = None
    return HttpResponse(json.dumps(services), content_type="application/json")


def form(request, uuid):
    form = get_object_or_404(Form.objects, pk=uuid)

    timestamp = request.session.get("form_token_timestamp", None)
    logout_delay = timedelta(minutes=settings.FORM_LOGOUT_DELAY_IN_MINUTES)
    if not timestamp or timezone.now().timestamp() - timestamp > logout_delay.total_seconds():
        request.session.pop("form_token_id", None)
    token_id = request.session.get("form_token_id")
    token = Token.objects.filter(pk=token_id).first() if token_id else None

    credential = None

    if form.is_closed():
        token = None
        code = None
    elif token:
        data = {k: quote(str(v)) for k, v in flatten(token.data, reducer="underscore").items()}
        if form.grant_credentials:
            with transaction.atomic():
                credential = Credential.objects.filter(form=form, token=token).first()
                if not credential:
                    credential = Credential.objects.filter(form=form, token__isnull=True).order_by('?').first()
                    credential.token = token
                    credential.state = Credential.State.ASSIGNED
                    credential.save(update_fields=["token", "state"])
            data['credential_login'] = credential.login
        code = form.code.format(**data)
    else:
        code = None

    action = request.GET.get("action")
    if action:
        if form.is_closed():
            return HttpResponseBadRequest("Form is closed")
        form_url = reverse("auth:form", args=(uuid,))
        if action == "login":
            request.session["token_id_field"] = "form_token_id"
            request.session["token_timestamp_field"] = "form_token_timestamp"
            request.session["token_url"] = form_url
            request.session["token_code_args"] = form.service_code_args
            return redirect(reverse("auth:query", args=(form.service.name,)))
        elif action == "logout":
            request.session.pop("form_token_id", None)
        elif action == "register":
            if request.headers.get("X-Secret") != form.secret:
                return HttpResponseBadRequest("Unauthorized")
            actions = []
            if form.grant_credentials:
                login = request.GET.get("login")
                credential = Credential.objects.get(form=form, login=login)
                credential.state = Credential.State.APPROVED
                credential.save(update_fields=["state"])
                actions.append({"name": "approve", "login": credential.login})
            if form.registration:
                register_url = form.register_url.format(**request.GET.dict())
                register_headers = form.register_headers.format(**request.headers)
                response = requests.post(register_url, headers=json.loads(register_headers))
                actions.append({"name": "register", "code": response.status_code, "text": response.text})
            return JsonResponse({"actions": actions})
        else:
            return HttpResponseBadRequest("Unknown action")
        return allowed_redirect(form_url)

    return render(
        request,
        "form.html",
        {
            "form": form,
            "code": code,
            "token": token,
            "credential": credential,
            "nofavicon": True,
            "nocounter": True,
        },
    )
