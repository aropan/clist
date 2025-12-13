from django.conf import settings
from django.conf.urls import include
from django.conf.urls.static import static as url_static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.templatetags.static import static
from django.urls import path, re_path
from django.views.generic import RedirectView, TemplateView

from pyclist.sitemaps import sitemaps
from pyclist.views import change_debug_toolbar, change_environment, charts

admin.autodiscover()

urlpatterns = [
    re_path(r'', include('clist.urls')),
    re_path(r'', include('my_oauth.urls')),
    re_path(r'', include('true_coders.urls')),
    re_path(r'', include('ranking.urls')),
    re_path(r'', include('events.urls')),
    re_path(r'', include('chats.urls')),
    re_path(r'', include('notification.urls')),
    re_path(r'', include('submissions.urls')),
    re_path(r'', include('donation.urls')),

    re_path(r'charts/', charts, name='charts'),
    re_path(r'change-environment/', change_environment, name='change_environment'),
    re_path(r'change-debug-toolbar/', change_debug_toolbar, name='change_debug_toolbar'),

    re_path(r'^telegram/', include('tg.urls')),

    re_path(r'^admin/doc/', include('django.contrib.admindocs.urls')),
    re_path(r'^admin/', admin.site.urls),

    re_path(r'^robots\.txt$', TemplateView.as_view(template_name='robots.txt', content_type='text/plain')),

    re_path(r'^googleee727737cf7b6a5a.html$', TemplateView.as_view(template_name='googleee727737cf7b6a5a.html')),

    re_path(r'^webpush/', include('webpush.urls')),

    path('o/', include('oauth2_provider.urls', namespace='oauth2_provider')),

    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),

    re_path(r'^privacy/$', TemplateView.as_view(template_name='privacy.html'), name='privacy'),
    re_path(r'^terms/$', TemplateView.as_view(template_name='terms.html'), name='terms'),
    re_path(r'^favicon/$', RedirectView.as_view(url=static('img/favicon/favicon-32x32.png')), name='favicon'),

    path('django-rq/', include('django_rq.urls')),

    path('silk/', include('silk.urls', namespace='silk')),
]


if settings.DEBUG:
    import debug_toolbar
    urlpatterns = (
        [re_path(r'^__debug__/', include(debug_toolbar.urls))]
        + url_static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
        + urlpatterns
    )
