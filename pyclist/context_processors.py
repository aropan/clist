from django.conf import settings


def global_settings(request):
    return {'vapid_public_key': settings.WEBPUSH_SETTINGS['VAPID_PUBLIC_KEY']}


def bootstrap_admin(request):
    return {'current_url': request.path}
