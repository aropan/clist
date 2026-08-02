from django.core.asgi import get_asgi_application


def get_application():
    django_asgi_app = get_asgi_application()

    from channels.auth import AuthMiddlewareStack
    from channels.routing import ProtocolTypeRouter, URLRouter
    from channels.security.websocket import OriginValidator
    from django.conf import settings

    import chats.routing
    import ranking.routing

    application = ProtocolTypeRouter({
        "http": django_asgi_app,
        "websocket": OriginValidator(
            AuthMiddlewareStack(
                URLRouter(chats.routing.websocket_urlpatterns + ranking.routing.websocket_urlpatterns),
            ),
            settings.WEBSOCKET_ALLOWED_ORIGINS,
        ),
    })

    return application


application = get_application()
