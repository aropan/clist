from django.conf import settings
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.middleware import csrf
from django.urls import reverse

from utils.request_logger import RequestLogger


def DebugPermissionOnlyMiddleware(get_response):

    def middleware(request):
        first_path = request.path.split('/')[1]
        if first_path not in ('static', 'imagefit', 'favicon.ico'):
            if not request.user.is_authenticated:
                if first_path not in ('login', 'signup', 'oauth', 'o', 'api', 'chats'):
                    return HttpResponseRedirect(reverse('auth:login') + f'?next={request.path}')
            elif not request.user.has_perm('auth.view_debug'):
                return HttpResponseForbidden()

        response = get_response(request)
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
