from django.urls import reverse
from django.http import HttpResponseRedirect, HttpResponseForbidden

from utils.request_logger import RequestLogger


def DebugPermissionOnlyMiddleware(get_response):

    def middleware(request):
        if not request.user.is_authenticated:
            first_path = request.path.split('/')[1]
            if first_path not in ('login', 'signup', 'oauth',):
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
