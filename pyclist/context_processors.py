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
        'host_url': settings.HTTPS_HOST_,
        'default_api_throttle_at': settings.DEFAULT_API_THROTTLE_AT_,
        'enable_global_rating': settings.ENABLE_GLOBAL_RATING_,
        'DEBUG': settings.DEBUG,
        'icons': settings.FONTAWESOME_ICONS_,
        'coder_list_n_values_limit': settings.CODER_LIST_N_VALUES_LIMIT_,
        'telegram_bot_name': settings.TELEGRAM_NAME,
    }


def bootstrap_admin(request):
    return {'current_url': request.path}


def coder_time_info(request):
    return {
        'timeformat': get_timeformat(request),
        'timezone': get_timezone(request),
    }
