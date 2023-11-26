from functools import partial

from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.middleware import csrf
from django.urls import reverse
from django.utils import timezone
from pytz import timezone as pytz_timezone

from clist.templatetags.extras import quote_url
from true_coders.models import Coder
from utils.request_logger import RequestLogger


def DebugPermissionOnlyMiddleware(get_response):

    def middleware(request):
        first_path = request.path.split('/')[1]
        if first_path not in settings.DEBUG_PERMISSION_EXCLUDE_PATHS:
            if not request.user.is_authenticated:
                if first_path not in ('login', 'signup', 'oauth', 'calendar', 'telegram'):
                    return HttpResponseRedirect(reverse('auth:login') + f'?next={quote_url(request.get_full_path())}')
            elif not request.user.has_perm('auth.view_debug'):
                return HttpResponseForbidden()

        response = get_response(request)
        if (
            response.status_code >= 400 and
            (not request.user.is_authenticated or not request.user.has_perm('auth.view_debug'))
        ):
            return HttpResponseForbidden()

        return response

    return middleware


def RequestLoggerMiddleware(get_response):

    def middleware(request):
        setattr(request, 'logger', RequestLogger(request))
        response = get_response(request)
        return response

    return middleware


def RequestIsAjaxFunction(get_response):

    def is_ajax(request):
        return request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'

    def middleware(request):
        setattr(request, 'is_ajax', partial(is_ajax, request))
        response = get_response(request)
        return response

    return middleware


def SetUpCSRFToken(get_response):

    def middleware(request):
        if not request.COOKIES.get(settings.CSRF_COOKIE_NAME):
            csrf.get_token(request)
        response = get_response(request)
        return response

    return middleware


def Lightrope(get_response):

    def middleware(request):
        lightrope = request.POST.get('lightrope')
        if lightrope in ['on', 'off', 'disable']:
            request.session['lightrope'] = lightrope
            if request.user.is_authenticated:
                coder = request.user.coder
                if coder.settings.get('lightrope') != lightrope:
                    coder.settings['lightrope'] = lightrope
                    coder.save()
            return HttpResponse('ok')

        response = get_response(request)
        return response

    return middleware


def SetAsCoder(get_response):

    def middleware(request):
        if request.GET.get('as_coder') and request.user.has_perm('as_coder'):
            as_coder_str = request.GET['as_coder']
            coder_filter = Q(user__username=as_coder_str)
            if as_coder_str.isdigit():
                coder_filter |= Q(pk=as_coder_str)
            as_coder = Coder.objects.get(coder_filter)
        else:
            as_coder = None
        setattr(request, 'as_coder', as_coder)
        response = get_response(request)
        return response

    return middleware


def UpdateCoderLastActivity(get_response):

    def middleware(request):
        response = get_response(request)
        if request.user.is_authenticated:
            coder = Coder.objects.filter(pk=request.user.coder.pk).first()
            if coder:
                coder.last_activity = timezone.now()
                coder.save(update_fields=['last_activity'])
        return response

    return middleware


class RedirectException(Exception):
    def __init__(self, redirect):
        self.redirect = redirect


class RedirectMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request, *args, **kwargs):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, RedirectException):
            return exception.redirect


class TimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            tzname = request.user.coder.timezone
            if tzname:
                timezone.activate(timezone.now().astimezone(pytz_timezone(tzname)).tzinfo)
            else:
                timezone.deactivate()
        return self.get_response(request)
