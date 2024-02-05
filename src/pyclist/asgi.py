from django.core.asgi import get_asgi_application
from django.core.cache import cache

from pyclist.decorators import run_only_in_production


@run_only_in_production
def reset_asgi_cache_values():
    cache.set('logify_ready', False)


def get_application():
    reset_asgi_cache_values()
    django_asgi_app = get_asgi_application()

    from channels.auth import AuthMiddlewareStack
    from channels.routing import ProtocolTypeRouter, URLRouter

    import chats.routing
    import ranking.routing

    application = ProtocolTypeRouter({
        'http': django_asgi_app,
        'websocket': AuthMiddlewareStack(
            URLRouter(
                chats.routing.websocket_urlpatterns +
                ranking.routing.websocket_urlpatterns
            ),
        ),
    })

    return application


application = get_application()
