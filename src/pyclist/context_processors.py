from django.conf import settings

from utils.timetools import get_timeformat, get_timezone


def global_settings(request):
    groupby = request.GET.get('groupby')
    return {
        'vapid_public_key': settings.WEBPUSH_SETTINGS['VAPID_PUBLIC_KEY'],
        'host_url': settings.HTTPS_HOST_URL_,
        'default_api_throttle_at': settings.DEFAULT_API_THROTTLE_AT_,
        'enable_global_rating': settings.ENABLE_GLOBAL_RATING_,
        'DEBUG': settings.DEBUG,
        'icons': settings.FONTAWESOME_ICONS_,
        'coder_list_n_values_limit': settings.CODER_LIST_N_VALUES_LIMIT_,
        'telegram_bot_name': settings.TELEGRAM_NAME,
        'unspecified_place': settings.STANDINGS_UNSPECIFIED_PLACE,
        'filter_field_suffix': settings.FILTER_FIELD_SUFFIX,
        'statistic_fields': set(settings.STANDINGS_STATISTIC_FIELDS),
        'account_fields': set(settings.ACCOUNT_STATISTIC_FIELDS),
        'scrollable_table': not request.user_agent.is_mobile and (not groupby or groupby == 'none'),
        'browser_family': request.user_agent.browser.family.lower(),
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
