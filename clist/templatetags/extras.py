import itertools
import json
import math
import re
from collections import OrderedDict, defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from os import path
from urllib.parse import quote_plus

import arrow
import pytz
import six
import yaml
from django import template
from django.conf import settings
from django.template.base import Node
from django.template.defaultfilters import floatformat, slugify, stringfilter
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
        return data[key] if -len(data) <= key < len(data) else None
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
def ifelse(value, default):
    value, cond = value
    return value if cond else default


@register.filter
def replace(value, new):
    value, old = value
    return value.replace(old, new)


@register.filter
def url(value):
    return reverse(value)


@register.filter
def parse_time(time):
    return arrow.get(time)


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
    d = (h + 12) // 24
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


@register.filter
def md_italic_escape(value):
    return value.replace('_', '_\\__')


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
    return slugify(unidecode(value)).strip('-')


@register.filter
def get_division_problems(problem, info):
    division = info.get('division')
    if division and 'division' in problem:
        return problem['division'][division]
    return problem


def get_problem_field(problem, field):
    if isinstance(problem, dict):
        return field in problem, problem.get(field)
    else:
        value = getattr(problem, field, None)
        return value is not None, value


@register.filter
def get_problem_key(problem):
    for k in ['code', 'short', 'name']:
        has, value = get_problem_field(problem, k)
        if has:
            return value


@register.filter
def get_problem_name(problem):
    for k in ['name', 'short', 'code']:
        has, value = get_problem_field(problem, k)
        if has:
            return value


@register.filter
def get_problem_short(problem):
    for k in ['short', 'code', 'name']:
        has, value = get_problem_field(problem, k)
        if has:
            return value


@register.filter
def add_prefix_to_problem_short(problem, prefix):
    for k in ['short', 'code', 'name']:
        if k in problem:
            problem[k] = prefix + problem[k]
            break


@register.filter
def get_problem_header(problem):
    if '_header' in problem:
        return problem[problem['_header']]
    for k in ['short', 'name', 'code']:
        has, value = get_problem_field(problem, k)
        if has:
            return value


@register.filter
def get_problem_title(problem):
    short = get_problem_header(problem)
    name = get_problem_name(problem)
    return f'{short}. {name}' if short != name else name


@register.simple_tag
def get_problem_solution(problem):
    ret = {}
    for contest in problem.contests.all():
        for statistic in contest.statistics_set.all():
            problems = contest.info.get('problems', [])
            if 'division' in problems:
                division = statistic.addition.get('division')
                problems = problems['division']
                if division not in problems:
                    continue
                problems = problems[division]

            ret = {'statistic': statistic}

            for p in problems:
                key = get_problem_key(p)
                if key == problem.key:
                    short = get_problem_short(p)
                    ret['result'] = statistic.addition.get('problems', {}).get(short)
                    ret['key'] = short
                    return ret
    return ret


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
    return countries.by_name(name) or countries.alpha2(name)


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


@register.filter
def get_new_rating_value(resource, value):
    *_, value = resource.get_rating_color(value, ignore_old=True)
    return value


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
    width = size // 10
    reverse_percent = resource.info.get('ratings', {}).get('reverse_circle_percent')
    if ('prev' if reverse_percent else 'next') not in rating:
        fill = f'<circle cx="{radius}" cy="{radius}" r="{size // 5}" style="fill: {color}"></circle>'
        title = f'{value}'
    else:
        prv = max(rating.get('prev', rating['low']), 0)
        nxt = rating.get('next', value)
        percent = (value - prv) / (nxt - prv)
        if reverse_percent:
            percent = 1 - percent
        v = percent * (size - 2 * width) + width
        fill = f'''
<path
    clip-path="url(#rating-clip-{size})"
    d="M 0 {size} v-{round(v, 3)} h {size} 0 v{size} z"
    style="fill: {color}"
/>
'''
        title = f'{value}'
        if 'next' in rating:
            title += f' ({percent * 100:.1f}%)'
    if 'name' in rating:
        title += f'<br/>{rating["name"]}'

    div_size = radius * 2 + width
    return mark_safe(
        f'''
        <div
            class="coder-circle"
            title="{title}"
            data-toggle="tooltip"
            data-html="true"
            style="display: inline-block; vertical-align: top; padding-top: 1px"
        >
            <div style="height: {div_size}px; ">
            <svg viewBox="-{width / 2} -{width / 2} {div_size} {div_size}" width="{div_size}" height="{div_size}">
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
    return mark_safe(json.dumps(data))


@register.filter
def chain(value, arg):
    return itertools.chain(value, arg)


@register.filter
def chain_rev(args, rev):
    if rev:
        args = reversed(args)
    return itertools.chain(*args)


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
    if isinstance(value, float):
        value_str = str(value)
        if '.' in value_str:
            length = len(value_str.split('.')[-1])
            if length > 3:
                return f'<span title="{value}" data-toggle="tooltip">{value:.3f}</span>'
    return value


@register.filter
def to_template_filter_value(value):
    if isinstance(value, bool):
        return str(value).lower()
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
        if value.get('partial'):
            return False
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


@register.simple_tag
def to_dict(**kwargs):
    return dict(**kwargs)


@register.filter
def as_number(value, force=False):
    valf = str(value).replace(',', '.')
    retf = asfloat(valf)
    if retf is not None:
        reti = toint(valf)
        if reti is not None:
            return reti
        return retf
    if valf and valf[-1] == '%':
        percentf = asfloat(valf[:-1])
        if percentf is not None:
            return percentf / 100
    if force:
        return None
    return value


@register.filter
def title_field(value):
    value = re.sub('([A-Z]+)', r'_\1', value)
    values = re.split('_+', value)
    value = ' '.join([v.title() for v in values])
    return value


@register.filter
def scoreformat(value):
    str_value = str(value)
    if not str_value or str_value[0] in ['+', '?']:
        return value
    format_value = floatformat(value, -2)
    return value if not format_value else format_value


@register.filter
def index(arr, value):
    return arr.index(value)


@register.filter
def contains(arr, value):
    return value in arr


@register.filter
def iftrue(val, ret=True):
    if val:
        return ret


@register.filter
def iffalse(val, ret=True):
    if not val:
        return ret


@register.filter
def time_in_seconds(timeline, val):
    times = re.split(r'[:\s]+', str(val))
    factors = timeline.get('time_factor', {}).get(str(len(times)))
    time = 0
    for idx, part in enumerate(times):
        val = asfloat(part)
        if val is None and (match := re.match(r'(?P<val>[0-9]+)(?P<factor>[дмчс])\.?', part)):
            val = asfloat(match.group('val'))
            factor = {'д': 24 * 60 * 60, 'ч': 60 * 60, 'м': 60, 'с': 1}[match.group('factor')]
            time += val * factor
        elif factors:
            time += val * factors[idx]
        else:
            time = time * 60 + val
    return time


def time_in_seconds_format(timeline, seconds, num=2):
    factors = timeline.get('time_factor', {})[str(num)]
    ret = []
    for idx, factor in enumerate(factors):
        val = seconds // factor
        seconds %= factor
        val = f'{val:02}' if idx else f'{val}'
        ret.append(val)
    return ':'.join(ret)


def get_country_from(context, country, custom_countries):
    if custom_countries and context['request'].user.is_authenticated and country.code in custom_countries:
        setattr(country, 'flag_code', custom_countries[country.code])
    else:
        setattr(country, 'flag_code', country.code)
    return country


@register.simple_tag(takes_context=True)
def get_country_from_account(context, account):
    return get_country_from(context, account.country, account.info.get('custom_countries_'))


@register.simple_tag(takes_context=True)
def get_country_from_coder(context, coder):
    return get_country_from(context, coder.country, coder.settings.get('custom_countries'))


@register.simple_tag
def use_lightrope():
    time = now()
    return time.month == 12 and time.day > 20 or time.month == 1 and time.day < 10


@register.simple_tag
def get_notification_messages_badges(user, path):
    if not user or user.is_anonymous or path == reverse('notification:messages'):
        return ''
    coder = getattr(user, 'coder', None)
    if not coder:
        return ''
    messages = coder.messages_set.filter(is_read=False)
    badges = defaultdict(int)
    for message in messages:
        badges[message.level or 'info'] += 1
    ret = []
    for badge, count in badges.items():
        ret.append(f'<span class="badge progress-bar-{badge}">{count}</span>')
    ret = '\n'.join(ret)
    return mark_safe(ret)


@register.filter
def filter_by_resource(coders, resource):
    ret = []
    seen = set()
    for coder in coders:
        opt = None
        for account in coder.resource_accounts:
            if account.resource_id != resource.pk:
                continue
            if opt is None or opt.n_contests < account.n_contests:
                opt = account
        if opt is None or opt.pk in seen:
            continue
        seen.add(opt.pk)
        ret.append(opt)
    return ret


@register.simple_tag
def trim_to(value, length):
    if not length or len(value) - 3 < length:
        return value
    half = length // 2
    trimmed_value = value[:half].strip() + '...' + value[-half:].strip()
    ret = f'<span title="{value}" data-toggle="tooltip">{trimmed_value}</span>'
    return mark_safe(ret)


@register.simple_tag
def win_probability(a, b):
    return 1 / (1 + 10 ** ((a - b) / 400))


@register.simple_tag
def rating_from_probability(b, p, min_rating=0, max_rating=5000):
    if p <= 0:
        return max_rating
    if p >= 1:
        return min_rating
    a = math.log10(1 / p - 1) * 400 + b
    return min(max(a, min_rating), max_rating)


@register.simple_tag
def icon_to(value, default=None, icons=None):
    icons = icons or settings.FONTAWESOME_ICONS_
    default = default or value.title()
    if value in icons:
        value = icons[value]
        if isinstance(value, dict):
            value, default = value['icon'], value.get('title', default)
        ret = f'<span title="{default}" data-toggle="tooltip">{value}</span>'
        return mark_safe(ret)
    else:
        return default
