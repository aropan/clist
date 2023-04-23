from django.conf import settings
from django.conf.urls import include, re_path
from django.conf.urls.static import static as url_static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.templatetags.static import static
from django.urls import path
from django.views.decorators.cache import cache_page
from django.views.generic import RedirectView, TemplateView

from pyclist.sitemaps import sitemaps
from pyclist.views import test

admin.autodiscover()

urlpatterns = [
    re_path(r'', include('clist.urls')),
    re_path(r'', include('my_oauth.urls')),
    re_path(r'', include('true_coders.urls')),
    re_path(r'', include('ranking.urls')),
    re_path(r'', include('events.urls')),
    re_path(r'', include('chats.urls')),
    re_path(r'', include('notification.urls')),

    re_path(r'^telegram/', include('tg.urls')),

    re_path(r'^admin/doc/', include('django.contrib.admindocs.urls')),
    re_path(r'^admin/', admin.site.urls),

    re_path(r'^robots\.txt$', TemplateView.as_view(template_name='robots.txt', content_type='text/plain')),

    re_path(r'^googleee727737cf7b6a5a.html$', TemplateView.as_view(template_name='googleee727737cf7b6a5a.html')),

    re_path(r'^webpush/', include('webpush.urls')),

    path('o/', include('oauth2_provider.urls', namespace='oauth2_provider')),

    path('sitemap.xml',
         sitemap if settings.DEBUG else cache_page(86400)(sitemap),
         {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),

    re_path(r'^privacy/$', TemplateView.as_view(template_name='privacy.html')),
    re_path(r'^favicon/$', RedirectView.as_view(url=static('img/favicon/favicon-32x32.png')), name='favicon'),
]


if settings.DEBUG:
    import debug_toolbar
    urlpatterns = (
        [
            re_path(r'^__debug__/', include(debug_toolbar.urls)),
            re_path(r'^__test__/', test, name='__test__'),
        ]
        + url_static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
        + urlpatterns
    )
