from datetime import timedelta, datetime
from os import path
from collections import OrderedDict
from collections.abc import Iterable
from unidecode import unidecode
import json
import re

from django import template
from django.urls import reverse
from django.conf import settings
from django.utils.safestring import mark_safe
from django.utils.timezone import now
from django.template.defaultfilters import stringfilter, slugify
from django_countries.fields import countries
import pytz


register = template.Library()


@register.filter
@stringfilter
def split(string, sep):
    return string.split(sep)


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.filter
def values_list_distinct(queryset, param):
    return [it[0] for it in queryset.values_list(param).distinct()]


@register.filter
def pass_arg(_1, _2):
    return _1, _2


@register.filter
def replace(value, new):
    value, old = value
    return value.replace(old, new)


@register.filter
def url(value):
    return reverse(value)


@register.filter
def timezone(time, tzname):
    return time.astimezone(pytz.timezone(tzname))


@register.filter
def format_time(time, fmt):
    return time.strftime(fmt)


@register.filter
def hr_timedelta(delta):
    if isinstance(delta, timedelta):
        delta = delta.total_seconds()
    if delta <= 0:
        return 'past'

    ret = []
    for c, s in (
        (364 * 24 * 60 * 60, 'year'),
        (7 * 24 * 60 * 60, 'week'),
        (24 * 60 * 60, 'day'),
        (60 * 60, 'hour'),
        (60, 'minute'),
        (1, 'second'),
    ):
        if c <= delta:
            val = delta // c
            ret.append('%d %s%s' % (val, s, 's' if val > 1 else ''))
            delta %= c
            if len(ret) == 2:
                break
    return ' '.join(ret)


@register.filter
def countdown(timer):
    if isinstance(timer, datetime):
        timer = (timer - now()).total_seconds()
    timer = int(timer)
    h = timer // 3600
    m = timer % 3600 // 60
    s = timer % 60
    d = (h + 12) / 24
    c = 0
    if d > 2:
        return "%d days" % d
    if m + h > 0:
        return "%02d:%02d:%02d" % (h, m, s)
    return "%d.%d" % (s, c)


@register.filter
def less_24_hours(time_delta):
    return time_delta < timedelta(hours=24)


@register.filter
def hours(time_delta):
    return time_delta.seconds // 3600


@register.filter
def minutes(time_delta):
    return time_delta.seconds % 3600 // 60


@register.filter
def get_timeanddate_href(datetime):
    return "https://www.timeanddate.com/worldclock/fixedtime.html?iso=" + datetime.strftime("%Y%m%dT%H%M")


@register.filter
def total_sub_contest(contests):
    return len([c for c in contests if hasattr(c, "sub_contest")])


@register.filter
def get_token(tokens, service):
    return tokens.filter(service=service).first()


@register.filter
def get_emails(tokens):
    if not tokens:
        return ""
    result = set()
    for token in tokens.all():
        result.add("'%s'" % token.email)
    return mark_safe(", ".join(result))


def get_timezones():
    with open(path.join(settings.STATIC_JSON_TIMEZONES), "r") as fo:
        return json.load(fo)


@register.simple_tag
def get_api_formats():
    return settings.TASTYPIE_DEFAULT_FORMATS


@register.filter
def md_escape(value):
    return re.sub(r'([*_`\[])', r'\\\1', value)


@register.filter(name='sort')
def listsort(value):
    if isinstance(value, dict):
        new_dict = OrderedDict()
        key_list = sorted(value.keys())
        for key in key_list:
            new_dict[key] = value[key]
        return new_dict
    elif isinstance(value, Iterable):
        return sorted(value)
    else:
        return value
    listsort.is_safe = True


@register.filter
def asfloat(value, default):
    try:
        return float(value)
    except ValueError:
        return default


@register.simple_tag
def calc_mod_penalty(info, contest, solving, penalty):
    time = min((now() - contest.start_time).total_seconds(), contest.duration_in_secs) // 60
    return int(round(penalty + (info['solving'] - solving) * time - info['penalty']))


@register.filter
def slug(value):
    return slugify(unidecode(value))


@register.filter
def get_division_problems(problem, info):
    division = info.get('division')
    if division and 'division' in problem:
        return problem['division'][division]
    return problem


@register.filter
def get_problem_key(problem):
    for k in ['short', 'code', 'name']:
        if k in problem:
            return problem[k]


@register.filter
def get_problem_name(problem):
    for k in ['name', 'short', 'code']:
        if k in problem:
            return problem[k]


@register.filter
def get_problem_short(problem):
    for k in ['short', 'name', 'code']:
        if k in problem:
            return problem[k]


@register.simple_tag
def define(val=None):
    return val


@register.simple_tag
def query_transform(request, *args, **kwargs):
    updated = request.GET.copy()
    if kwargs:
        updated.update(kwargs)
    if args:
        updated.update(dict(zip(args[::2], args[1::2])))
    return updated.urlencode()


@register.simple_tag
def get_countries():
    return dict((c.code, c) for c in countries).values()


@register.filter
def format_dict(format_, dict_values):
    return format_.format(**dict_values)


@register.filter
def has_season(key, name):
    return key.startswith(name) and re.match(r'^[-,\s0-9]+$', key[len(name):])


@register.filter
def strptime(val, form):
    return datetime.strptime(val, form)
