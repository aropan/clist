import itertools
import json
import re
from collections import OrderedDict, defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from os import path
from urllib.parse import quote_plus

import pytz
import six
import yaml
from django import template
from django.conf import settings
from django.template.base import Node
from django.template.defaultfilters import slugify, stringfilter
from django.urls import reverse
from django.utils.functional import keep_lazy
from django.utils.safestring import mark_safe
from django.utils.timezone import now
from django_countries.fields import countries
from unidecode import unidecode

register = template.Library()


@register.filter
@stringfilter
def split(string, sep):
    return string.split(sep)


@register.filter
def strip(string, val):
    return string.strip(val)


@register.filter
def get_item(data, key):
    if not data:
        return None
    if isinstance(data, (dict, defaultdict, OrderedDict)):
        return data.get(key)
    if isinstance(data, (list, tuple)):
        return data[key]
    return getattr(data, key, None)


@register.filter
def get_list(query_dict, key):
    return query_dict.getlist(key)


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
    if not time:
        return
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
            delta %= c
            ret.append('%d %s%s' % (val, s, 's' if val > 1 else ''))
        elif ret:
            ret.append('')
        if len(ret) == 2:
            break
    ret = ' '.join(ret)
    return ret.strip()


@register.filter
def countdown(timer):
    if isinstance(timer, datetime):
        timer = (timer - now()).total_seconds()
    if isinstance(timer, timedelta):
        timer = timer.total_seconds()
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
def timedelta_with_now(value):
    return value - now()


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
    for token in tokens:
        result.add("'%s'" % token.email)
    return mark_safe(", ".join(result))


def get_timezone_offset(tzname):
    total_seconds = now().astimezone(pytz.timezone(tzname)).utcoffset().total_seconds()
    return int(round(total_seconds / 60, 0))


@register.filter
def get_timezone_offset_hm(value):
    offset = get_timezone_offset(value)
    return f'{"+" if offset > 0 else "-"}{abs(offset // 60):02d}:{abs(offset % 60):02d}'


def get_timezones():
    with open(path.join(settings.STATIC_JSON_TIMEZONES), "r") as fo:
        timezones = json.load(fo)
        for tz in timezones:
            offset = get_timezone_offset(tz['name'])
            tz['offset'] = offset
            tz['repr'] = f'{"+" if offset > 0 else "-"}{abs(offset) // 60:02}:{abs(offset) % 60:02}'
    return timezones


@register.simple_tag
def get_api_formats():
    return settings.TASTYPIE_DEFAULT_FORMATS


@register.filter
def md_escape(value, clear=False):
    return re.sub(r'([*_`\[\]])', '' if clear else r'\\\1', value)


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
def asfloat(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


@register.filter
def aslist(value):
    if isinstance(value, (list, tuple)):
        return value
    return [value]


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
    for k in ['code', 'short', 'name']:
        if k in problem:
            return problem[k]


@register.filter
def get_problem_name(problem):
    for k in ['name', 'short', 'code']:
        if k in problem:
            return problem[k]


@register.filter
def get_problem_short(problem):
    for k in ['short', 'code', 'name']:
        if k in problem:
            return problem[k]


@register.filter
def add_prefix_to_problem_short(problem, prefix):
    for k in ['short', 'code', 'name']:
        if k in problem:
            problem[k] = prefix + problem[k]
            break


@register.filter
def get_problem_header(problem):
    for k in ['short', 'name', 'code']:
        if k in problem:
            return problem[k]


@register.simple_tag
def define(val=None):
    return val


@register.simple_tag
def query_transform(request, *args, **kwargs):
    updated = request.GET.copy()
    if args:
        kwargs.update(dict(zip(args[::2], args[1::2])))
    if kwargs:
        if kwargs.pop('with_replace', False):
            for k in kwargs:
                updated.pop(k, None)
        if kwargs.pop('with_remove', False):
            for k in kwargs:
                updated.pop(k, None)
            kwargs = {}
        updated.update(kwargs)

    if 'querystring_key' in updated:
        k = updated['querystring_key']
        if k in updated:
            updated.pop('querystring_key')
            updated.pop(k)

    return updated.urlencode()


@register.simple_tag
def url_transform(request, *args, **kwargs):
    query = query_transform(request, *args, **kwargs)
    return request.path + '?' + query


@register.simple_tag
def get_countries():
    ret = []
    for c in countries:
        if not re.search(r'[a-zA-Z]', c.name) or c.code in settings.DISABLED_COUNTRIES:
            continue
        override_names = settings.COUNTRIES_OVERRIDE.get(c.code, {}).get('names')
        if override_names and override_names[0] != c.name:
            continue
        ret.append(c)
    return ret


def is_country_code(val):
    return val is not None and len(val) == 2


@register.filter
def get_country_name(code):
    if code is None or not is_country_code(code):
        return code
    return countries.name(code)


@register.filter
def get_country_code(name):
    if name is None or is_country_code(name):
        return name
    return countries.by_name(name)


@register.filter
def format_dict(format_, dict_values):
    return format_.format(**dict_values)


@register.filter
def has_season(key, name):
    return key.startswith(name) and re.match(r'^[-,\s0-9]+$', key[len(name):])


@register.filter
def strptime(val, form):
    return datetime.strptime(val, form)


@register.filter
def get_rating(resource, value):
    rating, *_ = resource.get_rating_color(value)
    if not rating:
        return None
    return rating


@register.simple_tag
def coder_color_class(resource, *values):
    rating, *_ = resource.get_rating_color(values)
    if not rating:
        return ''
    return f'coder-color coder-{rating["color"]}'


@register.simple_tag
def coder_color_circle(resource, *values, size=16, **kwargs):
    rating, value = resource.get_rating_color(values)
    if not rating:
        return ''
    color = rating['hex_rgb']
    radius = size // 2
    width = size // 6
    if 'next' not in rating:
        fill = f'<circle cx="{radius}" cy="{radius}" r="{size // 5}" style="fill: {color}"></circle>'
        title = f'{value}'
    else:
        prv = max(rating['prev'], 0)
        nxt = rating['next']
        percent = (value - prv) / (nxt - prv)
        v = percent * (size - 2 * width) + width
        fill = f'''
<path
    clip-path="url(#rating-clip)"
    d="M 0 {size} v-{round(v, 3)} h {size} 0 v{size} z"
    style="fill: {color}"
/>
'''
        title = f'{value} ({percent * 100:.1f}%)'
    if 'name' in rating:
        title += f'<br/>{rating["name"]}'

    return mark_safe(
        f'''
        <div
            class="coder-circle"
            title="{title}"
            data-toggle="tooltip"
            data-html="true"
            style="display: inline-block; vertical-align: top; padding-top: 1px"
        >
            <div style="height: {size}px; ">
            <svg viewBox="0 0 {size} {size}" width="{size}" height="{size}">
                <circle
                    style="stroke: {color}; fill: none; stroke-width: {width}px;"
                    cx="{radius}"
                    cy="{radius}"
                    r="{radius - 1}"
                />
                {fill}
            </svg>
            </div>
        </div>
        ''')


@register.filter
def toint(val):
    try:
        return int(val)
    except Exception:
        return None


@register.filter(name='abs')
def abs_filter(val):
    try:
        return abs(val)
    except Exception:
        return None


@register.filter
def get_account(coder, host):
    return coder.get_account(host)


@register.filter
def get_type(value):
    return type(value).__name__


@register.filter
def order_by(value, orderby):
    return value.order_by(orderby)


@register.filter
def order_by_desc(value, orderby):
    return value.order_by('-' + orderby)


@register.filter
def limit(value, limit):
    return value[:limit]


@register.filter
def minimize(a, b):
    return min(a, b)


@register.filter
def get_number_from_str(val):
    if isinstance(val, (int, float)):
        return val
    if val is None:
        return
    val = re.sub(r'\s', '', str(val))
    match = re.search(r'-?[0-9]+(?:\.[0-9]+)?', str(val))
    if not match:
        return
    ret = yaml.safe_load(match.group(0))
    return ret


@register.filter
def resource_href(resource, host):
    return resource.href(host)


@register.filter
def url_quote(value):
    return quote_plus(value)


@register.filter
def multiply(value, arg):
    return value * arg


@register.filter
def divide(value, arg):
    return value / arg


@register.filter
def substract(value, arg):
    return value - arg


def canonize(data):
    return json.dumps(data, sort_keys=True)


@register.filter
def to_json(data):
    return json.dumps(data)


@register.filter
def chain(value, arg):
    return itertools.chain(value, arg)


@register.filter
def then(value, arg):
    return arg if value else None


@register.filter
def is_equal(value, arg):
    return value == arg


@register.filter
def concat(a, b):
    return str(a) + str(b)


@register.filter
def to_template_value(value):
    if isinstance(value, bool):
        return f'<i class="fas fa-{"check" if value else "times"}"></i>'
    return value


@register.filter(name='zip')
def zip_lists(a, b):
    return zip(a, b)


@register.filter
def startswith(text, starts):
    if isinstance(text, str):
        return text.startswith(starts)
    return False


@register.filter
def next_time_to(obj, now):
    return obj.next_time_to(now)


@register.filter
def is_solved(value):
    if not value:
        return False
    if isinstance(value, dict):
        value = value.get('result', 0)
    if isinstance(value, str):
        if value.startswith('+'):
            return True
        if value.startswith('-'):
            return False
        try:
            value = float(value)
        except ValueError:
            return False
    return value > 0


@register.filter
def timestamp_to_datetime(value):
    try:
        return datetime.fromtimestamp(value)
    except Exception:
        return None


@register.filter
def highlight_class(lang):
    if lang == 'python3':
        return 'python'
    return lang.replace(' ', '').lower()


@register.tag
def linebreakless(parser, token):
    nodelist = parser.parse(('endlinebreakless',))
    parser.delete_first_token()
    return LinebreaklessNode(nodelist)


class LinebreaklessNode(Node):
    def __init__(self, nodelist):
        self.nodelist = nodelist

    def render(self, context):
        strip_line_breaks = keep_lazy(six.text_type)(lambda x: x.replace('\n', ''))
        return strip_line_breaks(self.nodelist.render(context).strip())


@register.simple_tag
def call_method(obj, method_name, *args, **kwargs):
    method = getattr(obj, method_name)
    return method(*args, **kwargs)


@register.filter
def split_account_key(value, regex):
    if regex:
        match = re.search(regex, value)
        if match:
            st, fn = match.span()
            name = (value[:st] + value[fn:]).strip()
            subname = match.group('value')
            return name, subname
