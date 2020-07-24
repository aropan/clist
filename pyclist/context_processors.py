from django.conf import settings


def global_settings(request):
    return {
        'vapid_public_key': settings.WEBPUSH_SETTINGS['VAPID_PUBLIC_KEY'],
        'issues_url': settings.ISSUES_URL_,
        'news_url': settings.NEWS_URL_,
        'discuss_url': settings.DISCUSS_URL_,
    }


def bootstrap_admin(request):
    return {'current_url': request.path}
