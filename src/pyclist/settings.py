"""
Django settings for pyclist project.

Generated by 'django-admin startproject' using Django 1.8.2.

For more information on this file, see
https://docs.djangoproject.com/en/1.8/topics/settings/
For the full list of settings and their values, see
https://docs.djangoproject.com/en/1.8/ref/settings/
"""
import logging
import os
import warnings
from datetime import datetime

import pycountry
import sentry_sdk
from django.contrib.gis.geoip2 import GeoIP2
from django.core.paginator import UnorderedObjectListWarning
from django.utils.translation import gettext_lazy as _
from environ import Env
from pytz import utc
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from stringcolor import cs

from pyclist import conf

# disable UnorderedObjectListWarning when using autocomplete_fields
warnings.filterwarnings('ignore', category=UnorderedObjectListWarning)

# Build paths inside the project like this: path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

env = Env()
env.read_env(env('DJANGO_ENV_FILE'))
env.read_env(env('DJANGO_DB_CONF', default='/run/secrets/db_conf'))
env.read_env(env('DJANGO_SENTRY_CONF', default='/run/secrets/sentry_conf'))

ADMINS = conf.ADMINS

MANAGERS = ADMINS

EMAIL_HOST = conf.EMAIL_HOST
EMAIL_HOST_USER = conf.EMAIL_HOST_USER
EMAIL_HOST_PASSWORD = conf.EMAIL_HOST_PASSWORD
EMAIL_PORT = conf.EMAIL_PORT
EMAIL_USE_TLS = conf.EMAIL_USE_TLS

SERVER_EMAIL = 'Clist <%s>' % EMAIL_HOST_USER
DEFAULT_FROM_EMAIL = 'Clist <%s>' % EMAIL_HOST_USER

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.8/howto/deployment/checklist/

# Hosts/domain names that are valid for this site; required if DEBUG is False
# See https://docs.djangoproject.com/en/1.5/ref/settings/#allowed-hosts
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])

# SECURITY WARNING: keep the secret key used in production secret!

SECRET_KEY = conf.SECRET_KEY

# SECURITY WARNING: don't run with debug turned on in production!

DEV_ENV = 'dev'
PROD_ENV = 'prod'
ENVIRONMENT = env('DJANGO_ENV')
PYLINT_ENV = ENVIRONMENT == 'pylint'
DEBUG = ENVIRONMENT == DEV_ENV or PYLINT_ENV

# Application definition

INSTALLED_APPS = (
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.admindocs',
    'django.contrib.humanize',
    'django.contrib.sitemaps',
    'clist',
    'ranking',
    'tastypie',
    'my_oauth',
    'true_coders',
    'jsonify',  # https://pypi.python.org/pypi/django-jsonify/0.2.1
    'tastypie_swagger',
    'tg',
    'notification',
    'crispy_forms',
    'crispy_bootstrap3',
    'events',
    'django_countries',
    'el_pagination',
    'django_static_fontawesome',
    'django_extensions',
    'django_user_agents',
    'django_json_widget',
    'django_ltree',
    'webpush',
    'oauth2_provider',
    'channels',
    'chats',
    'favorites',
    'guardian',
    'django_rq',
    'notes',
    'logify',
    'fontawesomefree',
    'corsheaders',
    'submissions',
)

MIDDLEWARE = (
    'django.middleware.gzip.GZipMiddleware',
    'django_brotli.middleware.BrotliMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'pyclist.middleware.SetUpCSRFToken',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django_user_agents.middleware.UserAgentMiddleware',
    'csp.middleware.CSPMiddleware',
    'pyclist.middleware.UpdateCoderLastActivity',
    'pyclist.middleware.CustomRequestMiddleware',
    'pyclist.middleware.RequestIsAjaxFunction',
    'pyclist.middleware.RedirectMiddleware',
    'pyclist.middleware.TimezoneMiddleware',
    'pyclist.middleware.SetAsCoder',
    'pyclist.middleware.Lightrope',
    'pyclist.middleware.StatementTimeoutMiddleware',
)

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'guardian.backends.ObjectPermissionBackend',
)

if DEBUG:
    DEBUG_PERMISSION_EXCLUDE_PATHS = {'static'}
    MIDDLEWARE += (
        'pyclist.middleware.DebugPermissionOnlyMiddleware',
        'django_cprofile_middleware.middleware.ProfilerMiddleware',
    )
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

ROOT_URLCONF = 'pyclist.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': False,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'pyclist.context_processors.global_settings',
                'pyclist.context_processors.coder_time_info',
                'pyclist.context_processors.fullscreen',
                'pyclist.context_processors.favorite_settings',
            ],
            'builtins': [
                'pyclist.templatetags.staticfiles',
                'clist.templatetags.extras',
                'django.contrib.humanize.templatetags.humanize',
                'favorites.templatetags.favorites_extras',
                'django.templatetags.cache',
                'el_pagination.templatetags.el_pagination_tags',
            ],
            'loaders': [
                ('django.template.loaders.cached.Loader', [
                    'django.template.loaders.filesystem.Loader',
                    'django.template.loaders.app_directories.Loader',
                ]),
            ],
            'string_if_invalid': '',
            'debug': DEBUG,
        },
    },
]

WSGI_APPLICATION = 'pyclist.wsgi.application'

ASGI_APPLICATION = 'pyclist.asgi.application'

CHANNEL_LAYERS_CAPACITY = 10_000

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [('localhost', 6379)],
            'capacity': CHANNEL_LAYERS_CAPACITY,
        },
    },
}


# django_rq
RQ_QUEUES = {
    'default': {
        'HOST': 'localhost',
        'PORT': 6379,
        'DEFAULT_TIMEOUT': 3600,
    }
}
RQ_SHOW_ADMIN_LINK = True


# Database
# https://docs.djangoproject.com/en/1.8/ref/settings/#databases


DATABASES_ = {'postgresql': {'ENGINE': 'django.db.backends.postgresql_psycopg2'}}
if not PYLINT_ENV:
    DATABASES_['postgresql'].update({
        'NAME': env('POSTGRES_DB'),
        'USER': env('POSTGRES_USER'),
        'PASSWORD': env('POSTGRES_PASSWORD'),
        'HOST': env('POSTGRES_HOST'),
        'PORT': env('POSTGRES_PORT'),
    })

DATABASES = {
    'default': DATABASES_['postgresql'],
}
DATABASES.update(DATABASES_)


CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.memcached.PyMemcacheCache',
        'LOCATION': 'memcached:11211',
    }
}

USER_AGENTS_CACHE = 'default'


# Internationalization
# https://docs.djangoproject.com/en/1.8/topics/i18n/

LANGUAGE_CODE = 'en'

LANGUAGES = [
    ('en', _('English')),
]

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.8/howto/static-files/


STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
REPO_STATIC_ROOT = os.path.join(BASE_DIR, 'static/')
STATIC_JSON_TIMEZONES = os.path.join(BASE_DIR, 'static', 'json', 'timezones.json')
RESOURCES_ICONS_PATHDIR = 'img/resources/'
RESOURCES_ICONS_SIZES = [32, 64]

STATICFILES_STORAGE = 'static_compress.CompressedStaticFilesStorage'
STATIC_COMPRESS_METHODS = ['gz']


MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'mediafiles')
MEDIA_SIZES_PATHDIR = 'sizes/'

TASTYPIE_DEFAULT_FORMATS = ['json', 'jsonp', 'yaml', 'xml', 'plist']

LOGIN_URL = '/login/'

APPEND_SLASH = True

LOGGING = {
    'version': 1,
    'disable_existing_loggers': PYLINT_ENV,
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
        'require_debug_true': {
            '()': 'django.utils.log.RequireDebugTrue',
        },
    },
    'formatters': {
        'verbose': {
            'format': '[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        'db': {
            'format': str(cs('[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s', 'grey')),
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'null': {
            'level': 'DEBUG',
            'class': 'logging.NullHandler',
        },
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler',
        },
        'console_debug': {
            'level': 'DEBUG',
            'filters': ['require_debug_true'],
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'console_info': {
            'level': 'INFO',
            'filters': ['require_debug_false'],
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'db': {
            'level': 'DEBUG',
            'filters': ['require_debug_true'],
            'class': 'logging.StreamHandler',
            'formatter': 'db',
        },
        'development': {
            'level': 'DEBUG',
            'filters': ['require_debug_true'],
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'when': 'midnight',
            'interval': 1,
            'backupCount': 7,
            'filename': os.path.join(BASE_DIR, 'logs', 'dev.log'),
            'formatter': 'verbose',
            'delay': True,
        },
        'production': {
            'level': 'WARNING',
            'filters': ['require_debug_false'],
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'when': 'midnight',
            'interval': 1,
            'backupCount': 7,
            'filename': os.path.join(BASE_DIR, 'logs', 'prod.log'),
            'formatter': 'verbose',
            'delay': True,
        },
        'debug': {
            'level': 'DEBUG',
            'filters': ['require_debug_false'],
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'when': 'midnight',
            'interval': 1,
            'backupCount': 2,
            'filename': os.path.join(BASE_DIR, 'logs', 'debug.log'),
            'formatter': 'verbose',
            'delay': True,
        },
        'telegrambot': {
            'level': 'DEBUG',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'when': 'midnight',
            'interval': 1,
            'backupCount': 7,
            'filename': os.path.join(BASE_DIR, 'logs', 'telegram.log'),
            'formatter': 'verbose',
            'delay': True,
        },
    },
    'loggers': {
        **{
            k: {
                'handlers': ['null'],
                'propagate': False,
            }
            for k in (
                'django.security.DisallowedHost',
                'parso.python.diff',
                'PIL',
                'googleapiclient.discovery',
                'daphne',
                'asyncio',
                'numba.core',
            )
        },
        'django': {
            'handlers': ['mail_admins'],
            'level': 'ERROR',
        },
        'telegrambot': {
            'handlers': ['telegrambot'],
            'level': 'DEBUG',
        },
        'django.db.backends': {
            'handlers': ['db'],
            'level': 'DEBUG',
            'propagate': False,
        },
        '': {
            'handlers': ['console_debug', 'console_info', 'development', 'production', 'debug'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}


DATA_UPLOAD_MAX_NUMBER_FIELDS = 100000
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'


TELEGRAM_TOKEN = env('TELEGRAM_TOKEN', default=conf.TELEGRAM_TOKEN)
TELEGRAM_NAME = env('TELEGRAM_NAME', default=conf.TELEGRAM_NAME)
TELEGRAM_ADMIN_CHAT_ID = conf.TELEGRAM_ADMIN_CHAT_ID

CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap3'
CRISPY_TEMPLATE_PACK = 'bootstrap3'

COUNTRIES_OVERRIDE = {
    'CZ': {'names': ['Czech Republic', 'Czechia', 'Чехия']},
    'MK': {'names': ['Macedonia', 'North Macedonia', 'Македония']},
    'PS': {'names': ['Palestine', 'Palestine, State of', 'Палестина']},
    'KR': {'names': ['South Korea', 'Republic of Korea', 'Южная Корея', 'Korea, Republic of', 'Korea']},
    'MO': {'names': ['Macao', 'Macau', 'Макао']},
    'US': {'names': ['United States of America', 'United States', 'America', 'Virgin Islands', 'UM', 'United States Minor Outlying Islands', 'Соединенные Штаты Америки', 'США']},  # noqa
    'VN': {'names': ['Vietnam', 'Viet Nam', 'Вьетнам']},
    'GB': {'names': ['United Kingdom', 'United Kingdom of Great Britain', 'England', 'UK', 'Scotland', 'Northern Ireland', 'Wales', 'Великобритания', 'Англия', 'Шотландия']},  # noqa
    'MD': {'names': ['Moldova', 'Молдова', 'Молдавия', 'Republic of Moldova', 'Moldova, Republic of']},
    'KG': {'names': ['Kyrgyzstan', 'Кыргызстан', 'Киргизия']},
    'RS': {'names': ['Serbia', 'Srbija', 'Сербия']},
    'HR': {'names': ['Croatia', 'Hrvatska', 'Хорватия']},
    'CN': {'names': ['China', '中国', 'Китай']},
    'PL': {'names': ['Poland', 'Republic of Poland', 'Польша']},
    'RU': {'names': ['Russia', 'Россия', 'Russian Federation', 'Российская Федерация']},
    'SU': {'names': ['Soviet Union', 'Советский Союз']},
    'TR': {'names': ['Turkey', 'Türkiye', 'Турция']},
}
DISABLED_COUNTRIES = {'UM'}


ALPHA2_FIXES_MAPPING = {
    'AIDJ': 'A0',
    'BQAQ': 'B0',
    'BYAA': 'B1',
    'GEHH': 'G0',
    'SKIN': 'S0',
    'CSXX': 'Y0',
}

for country in pycountry.historic_countries:
    code = ALPHA2_FIXES_MAPPING.pop(country.alpha_4, country.alpha_2)
    assert not pycountry.countries.get(alpha_2=code)

    override = COUNTRIES_OVERRIDE.setdefault(code, {})
    assert not override.get('alpha3')
    names = [name.strip() for name in country.name.split(',')]
    assert names
    if names[-1].endswith(' of'):
        assert len(names) > 1
        names[-1] += ' ' + names[0]
    names = [name for name in names if not pycountry.countries.get(name=name)]

    override.setdefault('names', []).extend(names)
    if not pycountry.countries.get(alpha_3=country.alpha_3):
        override.setdefault('alpha3', country.alpha_3)
    if hasattr(country, 'numeric'):
        override.setdefault('numeric', country.numeric)


CUSTOM_COUNTRIES_ = getattr(conf, 'CUSTOM_COUNTRIES', {})
FILTER_CUSTOM_COUNTRIES_ = getattr(conf, 'FILTER_CUSTOM_COUNTRIES', {})


# guardian
ANONYMOUS_USER_NAME = None
GUARDIAN_AUTO_PREFETCH = True


# DJANGO DEBUG TOOLBAR
if DEBUG:
    MIDDLEWARE += ('debug_toolbar.middleware.DebugToolbarMiddleware',)
    INSTALLED_APPS += ('debug_toolbar',)

    DEBUG_TOOLBAR_DISABLE_PANELS = {
        'debug_toolbar.panels.templates.TemplatesPanel',
        'debug_toolbar.panels.redirects.RedirectsPanel',
        'debug_toolbar.panels.request.RequestPanel',
    }

    DEBUG_TOOLBAR_PANELS = [
        panel for panel in [
          'debug_toolbar.panels.history.HistoryPanel',
          'debug_toolbar.panels.versions.VersionsPanel',
          'debug_toolbar.panels.timer.TimerPanel',
          'debug_toolbar.panels.settings.SettingsPanel',
          'debug_toolbar.panels.headers.HeadersPanel',
          'debug_toolbar.panels.sql.SQLPanel',
          'debug_toolbar.panels.staticfiles.StaticFilesPanel',
          'debug_toolbar.panels.cache.CachePanel',
          'debug_toolbar.panels.signals.SignalsPanel',
          'debug_toolbar.panels.profiling.ProfilingPanel',
          'debug_toolbar.panels.templates.TemplatesPanel',
          'debug_toolbar.panels.redirects.RedirectsPanel',
          'debug_toolbar.panels.request.RequestPanel',
        ]
        if panel not in DEBUG_TOOLBAR_DISABLE_PANELS
    ]

    def show_toolbar_callback(request):
        first_path = request.path.split('/')[1]
        return (
            first_path not in DEBUG_PERMISSION_EXCLUDE_PATHS and
            not request.is_ajax() and
            'disable_djtb' not in request.GET and
            (not DEBUG or request.user.is_authenticated)
        )

    DEBUG_TOOLBAR_CONFIG = {
        'SHOW_TOOLBAR_CALLBACK': show_toolbar_callback,
        'DISABLE_PANELS': DEBUG_TOOLBAR_DISABLE_PANELS,
    }

# WEBPUSH
WEBPUSH_SETTINGS = conf.WEBPUSH_SETTINGS

# OAUTH2 PROVIDER
OAUTH2_PROVIDER = {
    'DEFAULT_SCOPES': ['read'],
}


CSRF_COOKIE_SECURE = True

# HTTP Strict Transport Security
SECURE_HSTS_SECONDS = 15768000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# CORS
CORS_ALLOW_ALL_ORIGINS = True
CORS_URLS_REGEX = '^/api/.*$'

# Content Security Policy
CSP_DEFAULT_SRC = ("'self'", "'unsafe-inline'", "'unsafe-eval'", "https:", "data:")
CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'", "'unsafe-eval'")
CSP_IMG_SRC = CSP_DEFAULT_SRC
CSP_CONNECT_SRC = CSP_DEFAULT_SRC

# CSP Yandex counter
CSP_SCRIPT_SRC += ('https://mc.yandex.ru', 'https://yastatic.net', )
CSP_IMG_SRC += ('https://mc.yandex.ru', )
CSP_CONNECT_SRC += ('https://mc.yandex.ru', )

# CSP Google counter
CSP_SCRIPT_SRC += ('https://www.google-analytics.com', 'https://www.googletagmanager.com', )
CSP_IMG_SRC += ('https://www.google-analytics.com', )
CSP_CONNECT_SRC += ('https://www.google-analytics.com', )

# X-XSS-Protection
SECURE_BROWSER_XSS_FILTER = True

# CONSTANTS
VIEWMODE_ = 'list'
OPEN_NEW_TAB_ = False
ADD_TO_CALENDAR_ = 'enable'
COUNT_PAST_ = 3
GROUP_LIST_ = True
HIDE_CONTEST_ = False
FAVORITE_SETTINGS_ = {
    'contests': True,
    'problems': True,
}
DEFAULT_TIME_ZONE_ = 'UTC'
CHANING_HOSTS_ = ['clist.by', 'dev.clist.by']
HOST_ = 'dev.clist.by' if DEBUG else 'clist.by'
HTTPS_HOST_URL_ = 'https://' + HOST_
MAIN_HOST_URL_ = 'https://clist.by'
CLIST_RESOURCE_DICT_ = {
    'host': HOST_,
    'pk': 0,
    'icon': 'img/favicon/favicon-32x32.png',
    'kind': 'global_rating',
    'colors': [],
}
EMAIL_PREFIX_SUBJECT_ = '[Clist] '
STOP_EMAIL_ = getattr(conf, 'STOP_EMAIL', False)
TIME_FORMAT_ = '%d.%m %a %H:%M'
LIMIT_N_TOKENS_VIEW = 3
LIMIT_TOKENS_VIEW_WAIT_IN_HOURS = 24
YES_ = {'', '1', 'yes', 'y', 'true', 't', 'on'}
NONE_ = {'null', 'none'}
ACE_CALENDARS_ = {
    'enable': {'id': 'enable', 'name': 'Enable'},
    'disable': {'id': 'disable', 'name': 'Disable'},
    'google': {'id': 1, 'name': 'Google'},
    'yahoo': {'id': 2, 'name': 'Yahoo'},
    'outlook': {'id': 3, 'name': 'Outlook'},
}
PAST_CALENDAR_ACTIONS_ = ['show', 'lighten', 'darken', 'lighten-day', 'darken-day', 'hide']
PAST_CALENDAR_DEFAULT_ACTION_ = 'lighten'
ORDERED_MEDALS_ = ['gold', 'silver', 'bronze']
THEMES_ = ['default', 'cerulean', 'cosmo', 'cyborg', 'darkly', 'flatly', 'journal', 'lumen', 'paper', 'readable',
           'sandstone', 'simplex', 'slate', 'spacelab', 'superhero', 'united', 'yeti']
SESSION_DURATIONS_ = {
    '1 day': {'value': 60 * 60 * 24},
    '1 week': {'value': 60 * 60 * 24 * 7},
    '1 month': {'value': 60 * 60 * 24 * 30, 'default': True},
    '1 year': {'value': 60 * 60 * 24 * 365},
    '1 life': {'value': datetime.max.replace(tzinfo=utc)},

}

DEFAULT_COUNT_QUERY_ = 10
DEFAULT_COUNT_LIMIT_ = 100

ADDITION_HIDE_FIELDS_ = {'problems', 'solved', 'hack', 'challenges', 'url'}

VIRTUAL_CODER_PREFIX_ = '∨'

DEFAULT_API_THROTTLE_AT_ = 10

CODER_LIST_N_VALUES_LIMIT_ = 100

ENABLE_GLOBAL_RATING_ = DEBUG

FONTAWESOME_ICONS_ = {
    'institution': '<i class="fa-fw fas fa-university"></i>',
    'country': '<i class="fab fa-font-awesome-flag"></i>',
    'room': '<i class="fa-fw fas fa-door-open"></i>',
    'affiliation': '<i class="fa-fw fas fa-user-friends"></i>',
    'city': '<i class="fa-fw fas fa-city"></i>',
    'school': '<i class="fa-fw fas fa-school"></i>',
    'class': '<i class="fa-fw fas fa-user-graduate"></i>',
    'job': '<i class="fa-fw fas fa-building"></i>',
    'rating': '<i class="fa-fw fas fa-chart-line"></i>',
    'medal': '<i class="fa-fw fas fa-medal"></i>',
    'region': '<i class="fa-fw fas fa-map-signs"></i>',
    'chat': '<i class="fa-fw fas fa-user-friends"></i>',
    'advanced': '<i class="fa-fw far fa-check-circle"></i>',
    'company': '<i class="fa-fw fas fa-building"></i>',
    'language': '<i class="fa-fw fas fa-code"></i>',
    'languages': '<i class="fa-fw fas fa-code"></i>',
    'verdicts': '<i class="fas fa-scroll"></i>',
    'league': '<i class="fa-fw fas fa-chess"></i>',
    'degree': '<i class="fa-fw fas fa-user-graduate"></i>',
    'university': '<i class="fa-fw fas fa-university"></i>',
    'list': '<i class="fa-fw fas fa-list"></i>',
    'group': '<i class="fa-fw fas fa-user-friends"></i>',
    'group_ex': '<i class="fa-fw fas fa-user-friends"></i>',
    'college': '<i class="fa-fw fas fa-university"></i>',
    'resource': '<i class="fa-fw fas fa-at"></i>',
    'field': '<i class="fa-fw fas fa-database"></i>',
    'database': '<i class="fas fa-database"></i>',
    'find_me': '<i class="fa-fw fas fa-crosshairs"></i>',
    'search': '<i class="fa-fw fas fa-search"></i>',
    'detail_info': '<i class="fa-fw fas fa-info"></i>',
    'short_info': '<i class="fa-fw fas fa-times"></i>',
    'score_in_row': '<i class="fa-fw fas fa-balance-scale"></i>',
    'luck': '<i class="fa-fw fas fa-dice"></i>',
    'tag': '<i class="fa-fw fas fa-tag"></i>',
    'hide': '<i class="fa-fw far fa-eye-slash"></i>',
    'show': '<i class="fa-fw far fa-eye"></i>',
    'delete': '<i class="fa-fw far fa-trash-alt"></i>',
    'period': '<i class="fa-fw far fa-clock"></i>',
    'date': '<i class="fa-fw far fa-calendar-alt"></i>',
    'n_participations': {'icon': '<i class="fa-fw fas fa-running"></i>', 'title': 'Number of participations'},
    'chart': '<i class="fa-fw fas fa-chart-bar"></i>',
    'ghost': '<i class="fs-fw fas fa-ghost"></i>',
    'top': '<i class="fas fa-list-ol"></i>',
    'accounts': '<i class="fa-regular fa-rectangle-list"></i>',
    'problems': '<i class="fa-solid fa-list-check"></i>',
    'submissions': '<i class="fa-solid fa-bars"></i>',
    'versus': '<i class="fas fa-people-arrows"></i>',
    'last_activity': '<i class="fa-fw far fa-clock"></i>',
    'fullscreen': '<i class="fas fa-expand-arrows-alt"></i>',
    'update': '<i class="fas fa-sync"></i>',
    'open_in_tab': '<i class="fas fa-external-link-alt"></i>',
    'extra_url': '<i class="fas fa-external-link-alt"></i>',
    'copy': '<i class="far fa-copy"></i>',
    'copied': '<i class="fas fa-copy"></i>',
    'pin': '<i class="far fa-star"></i>',
    'unpin': '<i class="fas fa-star"></i>',
    'timeline': '<i class="fas fa-history"></i>',
    'contest': '<i class="fas fa-laptop-code"></i>',
    'kofi': {'icon': '<i class="fas fa-mug-hot ko-fi"></i>', 'title': None},
    'crypto': {'icon': '<i class="fab fa-bitcoin"></i>', 'title': None},
    'fav': {'icon': '<i class="fas fa-star activity fav selected-activity"></i>', 'title': 'Favorite',
            'name': 'fa-star', 'unselected_class': 'far', 'check_field': 'is_favorite'},
    'unfav': {'icon': '<i class="far fa-star activity fav"></i>', 'title': None},
    'sol': {'icon': '<i class="fas fa-check activity sol"></i>', 'name': 'fa-check', 'check_field': 'is_solved'},
    'rej': {'icon': '<i class="fas fa-times activity rej"></i>', 'name': 'fa-times', 'check_field': 'is_reject'},
    'tdo': {'icon': '<i class="fas fa-calendar-day activity tdo"></i>', 'name': 'fa-calendar-day',
            'check_field': 'is_todo'},
    'allsolved': {'icon': '<i class="far fa-check-circle sol"></i>', 'name': 'fa-check-circle',
                  'selected_class': 'far', 'unselected_class': 'far'},
    'allreject': {'icon': '<i class="far fa-times-circle rej"></i>', 'name': 'fa-times-circle',
                  'selected_class': 'far', 'unselected_class': 'far'},
    'status': '<i class="far fa-lightbulb"></i>',
    'n_participants': {'icon': '<i class="fas fa-users"></i>', 'title': 'Number of participants', 'position': 'bottom'},
    'n_problems': {'icon': '<i class="fa-solid fa-list-check"></i>', 'title': 'Number of problems',
                   'position': 'bottom'},
    'series': '<i class="fas fa-trophy"></i>',
    'app': '<i class="fas fa-desktop"></i>',
    'sort-asc': '<i class="fas fa-sort-amount-down-alt"></i>',
    'sort-desc': '<i class="fas fa-sort-amount-down"></i>',
    'verification': '<i class="far fa-check-circle"></i>',
    'verified': '<i class="verified fas fa-check-circle"></i>',
    'unverified': '<i class="unverified fas fa-check-circle"></i>',
    'ips': '<i class="fas fa-user-secret"></i>',
    'secret': '<i class="fas fa-user-secret"></i>',
    'log': '<i class="fas fa-scroll"></i>',
    'on': '<i class="fa-fw fas fa-toggle-on"></i>',
    'off': '<i class="fa-fw fas fa-toggle-off"></i>',
    'more': '<i class="fa-fw fas fa-ellipsis-h"></i>',
    'note': {'icon': '<i class="far fa-edit"></i>', 'name': 'fa-edit', 'check_field': 'is_note',
             'selected_class': 'far note-edit', 'unselected_class': 'far note-edit'},
    'badge': {'icon': '<i class="fas fa-tag"></i>'},
    'virtual': '<i class="fas fa-globe"></i>',
    'private': '<span class="label label-success"><i class="fa-solid fa-lock"></i></span>',
    'restricted': '<span class="label label-warning"><i class="fa-solid fa-unlock"></i></span>',
    'public': '<span class="label label-danger"><i class="fa-solid fa-lock-open"></i></span>',
    'as_coder': '<i class="fa-solid fa-user-group"></i>',
    'logify': '<i class="fa-regular fa-file-lines"></i>',
    'is_virtual': {'icon': '<i class="fa-solid fa-clock-rotate-left"></i>', 'title': False},
    'to_list': {'icon': '<i class="fa-solid fa-list-check"></i>', 'title': 'Add to list'},
    'invert': '<i class="fa-solid fa-rotate"></i>',
    'stage': '<i class="fa-regular fa-object-group"></i>',
    'full_table': {'icon': '<i class="fa-solid fa-up-down"></i>', 'title': 'Load full table'},
    'charts': '<i class="fa-solid fa-chart-line"></i>',
    'dev': '<i class="fa-regular fa-clone"></i>',
    'medal_scores': '<i class="fa-fw fas fa-chart-line"></i>',
    'merged_standings': '<i class="fa-solid fa-object-group"></i>',
    'finish': '<i class="fa-solid fa-flag-checkered"></i>',
    'virtual_start': '<i class="fa-solid fa-stopwatch"></i>',
    'unfreezing': '<i class="fa-regular fa-snowflake"></i>',
    'exclamation': '<i class="fa-solid fa-circle-exclamation"></i>',
    'close': '<i class="fa-solid fa-xmark"></i>',

    'google': {'icon': '<i class="fab fa-google"></i>', 'title': None},
    'facebook': {'icon': '<i class="fab fa-facebook"></i>', 'title': None},
    'youtube': {'icon': '<i class="fab fa-youtube"></i>', 'title': None},
    'twitch': {'icon': '<i class="fab fa-twitch"></i>', 'title': None},
    'github': {'icon': '<i class="fab fa-github"></i>', 'title': None},
    'yandex': {'icon': '<i class="fab fa-yandex-international"></i>', 'title': None},
    'discord': {'icon': '<i class="fab fa-discord"></i>', 'title': None},
    'vk': {'icon': '<i class="fab fa-vk"></i>', 'title': None},
    'patreon': {'icon': '<i class="fab fa-patreon"></i>', 'title': None},
    'competitive-hustle': {'icon': '<i class="fas fa-tools"></i>'},
}


STANDINGS_FIELDS_ = {
    'n_gold_problems': '<span class="trophy trophy-detail gold-trophy"><i class="fas fa-trophy"></i></span>',
    'n_silver_problems': '<span class="trophy trophy-detail silver-trophy"><i class="fas fa-trophy"></i></span>',
    'n_bronze_problems': '<span class="trophy trophy-detail bronze-trophy"><i class="fas fa-trophy"></i></span>',
}

STANDINGS_SMALL_N_STATISTICS = 1000
STANDINGS_FREEZE_DURATION_FACTOR_DEFAULT = 0.2

UPSOLVING_FILTER_DEFAULT = True

GEOIP_PATH = os.path.join(BASE_DIR, 'sharedfiles', 'GeoLite2-Country.mmdb')
GEOIP_ACCOUNT_ID = getattr(conf, 'GEOIP_ACCOUNT_ID')
GEOIP_LICENSE_KEY = getattr(conf, 'GEOIP_LICENSE_KEY')

GEOIP = None
if os.path.exists(GEOIP_PATH):
    GEOIP = GeoIP2(GEOIP_PATH)
elif GEOIP_ACCOUNT_ID or GEOIP_LICENSE_KEY:
    logging.warning('GeoIP database not found. Run ./manage.py download_geoip_database to download it.')


class NOTIFICATION_CONF:
    EMAIL = 'email'
    TELEGRAM = 'telegram'
    WEBBROWSER = 'webbrowser'

    METHODS_CHOICES = (
        (EMAIL, 'Email'),
        (TELEGRAM, 'Telegram'),
        (WEBBROWSER, 'WebBrowser'),
    )


SHELL_PLUS_IMPORTS = [
    ('django.core.management', 'call_command'),
    ('collections', 'defaultdict'),
    ('tqdm'),
]


# Sentry
if not DEBUG:
    sentry_sdk.init(
        dsn=env('SENTRY_DSN'),
        integrations=[
            DjangoIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        traces_sample_rate=0.01,
        profiles_sample_rate=0.01,
        send_default_pii=True,
        environment='development' if DEBUG else 'production',
    )
