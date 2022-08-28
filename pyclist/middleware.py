from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.middleware import csrf
from django.urls import reverse
from django.utils.timezone import now

from true_coders.models import Coder
from utils.request_logger import RequestLogger


def DebugPermissionOnlyMiddleware(get_response):

    def middleware(request):
        first_path = request.path.split('/')[1]
        if first_path not in settings.DEBUG_PERMISSION_EXCLUDE_PATHS:
            if not request.user.is_authenticated:
                if first_path not in ('login', 'signup', 'oauth', 'calendar'):
                    return HttpResponseRedirect(reverse('auth:login') + f'?next={request.path}')
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
            as_coder = Coder.objects.get(user__username=request.GET['as_coder'])
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
            coder = request.user.coder
            coder.last_activity = now()
            coder.save(update_fields=['last_activity'])
        return response

    return middleware
