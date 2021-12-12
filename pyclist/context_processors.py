from django.conf import settings

from clist.views import get_timeformat, get_timezone


def global_settings(request):
    return {
        'vapid_public_key': settings.WEBPUSH_SETTINGS['VAPID_PUBLIC_KEY'],
        'issues_url': settings.ISSUES_URL_,
        'news_url': settings.NEWS_URL_,
        'discuss_url': settings.DISCUSS_URL_,
        'donate_url': settings.DONATE_URL_,
        'main_host_url': settings.MAIN_HOST_,
        'DEBUG': settings.DEBUG,
    }


def bootstrap_admin(request):
    return {'current_url': request.path}


def coder_time_info(request):
    return {
        'timeformat': get_timeformat(request),
        'timezone': get_timezone(request),
    }
