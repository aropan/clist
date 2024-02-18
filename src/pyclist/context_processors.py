from django.conf import settings

from clist.views import get_timeformat, get_timezone


def global_settings(request):
    return {
        'vapid_public_key': settings.WEBPUSH_SETTINGS['VAPID_PUBLIC_KEY'],
        'main_host_url': settings.MAIN_HOST_URL_,
        'host_url': settings.HTTPS_HOST_URL_,
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


def favorite_settings(request):
    context = {}
    for content_type, favorite_result in settings.FAVORITE_SETTINGS_.items():
        favorite_key = f'favorite_{content_type}'
        if request.user.is_authenticated:
            favorite_result = request.user.coder.settings.get(favorite_key, favorite_result)
        favorite_result = request.GET.get(favorite_key, favorite_result)
        favorite_result = int(str(favorite_result).lower() in settings.YES_)
        context[favorite_key] = favorite_result
    return context


def fullscreen(request):
    return {'fullscreen': request.GET.get('fullscreen') in settings.YES_}
