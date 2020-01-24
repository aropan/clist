from django.conf.urls import include, url
from django.conf import settings
from django.views.generic import TemplateView
from django.contrib import admin


admin.autodiscover()


urlpatterns = [
    url(r'', include('clist.urls')),
    url(r'', include('my_oauth.urls')),
    url(r'', include('true_coders.urls')),
    url(r'', include('ranking.urls')),
    url(r'', include('events.urls')),

    url(r'^markdown/', include('django_markdown.urls')),
    url(r'^telegram/', include('tg.urls')),

    url(r'^admin/doc/', include('django.contrib.admindocs.urls')),
    url(r'^admin/', admin.site.urls),

    url(r'^robots\.txt$', TemplateView.as_view(template_name='robots.txt', content_type='text/plain')),

    url(r'^googleee727737cf7b6a5a.html$', TemplateView.as_view(template_name='googleee727737cf7b6a5a.html')),

    url(r'^debug/', TemplateView.as_view(template_name='debug.html'), name='debug'),
]


if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [
        url(r'^__debug__/', include(debug_toolbar.urls)),
    ] + urlpatterns
