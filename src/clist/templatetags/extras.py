import itertools
import json
import math
import os
import re
from collections import OrderedDict, defaultdict
from collections.abc import Iterable
from copy import deepcopy
from datetime import datetime, timedelta
from functools import reduce
from sys import float_info
from urllib.parse import quote_plus, urlparse

import arrow
import pytz
import six
import yaml
from django import template
from django.apps import apps
from django.conf import settings
from django.db.models import Value
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
        if key in data:
            return data.get(key)
    elif isinstance(data, (list, tuple)):
        key_as_number = as_number(key, force=True)
        if key_as_number is not None and -len(data) <= key_as_number < len(data):
            return data[key_as_number]
    elif hasattr(data, key):
        return getattr(data, key)
    for sep in ('.', '__'):
        if sep in str(key):
            return reduce(lambda d, k: get_item(d, k) if d else None, str(key).split(sep), data)
    return None


@register.simple_tag
def set_item(data, key, value):
    data[key] = value
    return ''


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
def hr_timedelta(delta, n_significant=2):
    if isinstance(delta, timedelta):
        delta = delta.total_seconds()
    if delta <= 0:
        return 'past'

    ret = []
    n_used = 0
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
            n_used += 1
        elif ret:
            n_used += 1
        if n_significant and n_significant == n_used:
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
def is_coming(value):
    return value > now()


@register.filter
def is_past(value):
    return value < now()


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
    with open(os.path.join(settings.STATIC_JSON_TIMEZONES), "r") as fo:
        timezones = json.load(fo)
        for tz in timezones:
            offset = get_timezone_offset(tz['name'])
            tz['offset'] = offset
            tz['repr'] = f'{"+" if offset >= 0 else "-"}{abs(offset) // 60:02}:{abs(offset) % 60:02}'
    return timezones


@register.simple_tag
def get_api_formats():
    return settings.TASTYPIE_DEFAULT_FORMATS


@register.filter
def md_escape(value, clear=False):
    ret = ' ' + value
    repl = r'\1' if clear else r'\1\\\2'
    ret = re.sub(r'([^\\])([*_`\[])', repl, ret)
    ret = ret[1:]
    return ret


@register.filter
def md_url(value, clear=False):
    return value.replace('(', '%28').replace(')', '%29')


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
def get_division_problems(problems, info):
    ret = []
    if 'division' in problems:
        division_addition = info.get('_division_addition')
        divisions = list(division_addition.keys()) if division_addition else []
        division = info.get('division')
        if division and division not in divisions:
            divisions = [division] + divisions
        for division in divisions:
            if division in problems['division']:
                for problem in problems['division'][division]:
                    ret.append(problem)
    return ret or problems


def get_problem_field(problem, field):
    if isinstance(problem, dict):
        has, ret = field in problem, problem.get(field)
    else:
        value = getattr(problem, field, None)
        has, ret = value is not None, value
    if has and ret:
        ret = str(ret)
    return has, ret


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
            problems = get_division_problems(problems, statistic.addition)
            group_scores = defaultdict(int)

            for p in problems:
                key = get_problem_key(p)
                if key == problem.key:
                    short = get_problem_short(p)
                    result = deepcopy(statistic.addition.get('problems', {}).get(short))

                    if 'group' in p:
                        if is_solved(result):
                            score = as_number(result.get('result'))
                            if score is not None:
                                group_scores[p['group']] += score
                                result['result'] = group_scores[p['group']]

                    res = {'statistic': statistic, 'result': result, 'key': short}
                    if (
                        not ret or ret['result'] is None or
                        result is not None and is_improved_solution(result, ret['result'])
                    ):
                        ret = res
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
def query_fields(request, *args, before='&'):
    updated = request.GET.copy()
    for k in list(updated.keys()):
        if k not in args:
            updated.pop(k)
    ret = updated.urlencode()
    if ret:
        ret = before + ret
    return ret


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
    Account = apps.get_model('ranking', 'Account')
    cleaned_values = [a.info if isinstance(a, Account) else a for a in values]
    rating, value = resource.get_rating_color(cleaned_values)
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
    if len(values) == 1 and isinstance(values[0], Account):
        resource_rank = values[0].resource_rank
        if resource_rank:
            total_rank = resource.n_rating_accounts
            percent = resource_rank * 100 / total_rank
            percent = format_to_significant_digits(percent, 2)
            title += f'<br/>#{resource_rank} of {total_rank} ({percent}%)'

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
    return coder.get_account(host) if coder is not None else None


@register.filter
def get_type(value):
    return type(value).__name__


@register.filter
def order_by(value, orderby):
    return value.order_by(orderby)


@register.filter
def order_by_desc(value, orderby):
    return value.order_by(f'-{orderby}')


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


@register.filter
def mod(value, arg):
    return value % arg


def canonize(data):
    return json.dumps(data, sort_keys=True)


@register.filter
def to_json(data):
    return mark_safe(json.dumps(data))


@register.filter
def to_escaped_json(data):
    return json.dumps(data)


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
def to_str(value):
    return str(value)


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
def is_solved(value, with_upsolving=False):
    if not value:
        return False
    if isinstance(value, dict):
        if with_upsolving and is_solved(value.get('upsolving')):
            return True
        if value.get('partial'):
            return False
        if value.get('binary') is True:
            return True
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
def is_reject(value, with_upsolving=False):
    if with_upsolving and is_solved(value, with_upsolving=with_upsolving):
        return False
    if isinstance(value, dict):
        if with_upsolving and is_reject(value.get('upsolving')):
            return True
        if value.get('binary') is False:
            return True
        value = value.get('result')
    if not value:
        return False
    if str(value).startswith('-'):
        return True
    try:
        value = float(value)
    except ValueError:
        return False
    return value <= 0


@register.filter
def is_upsolved(value):
    if not value:
        return False
    return is_solved(value.get('upsolving'))


@register.filter
def is_hidden(value, with_upsolving=False):
    if with_upsolving and is_solved(value, with_upsolving=with_upsolving):
        return False
    if isinstance(value, dict):
        if with_upsolving and is_hidden(value.get('upsolving')):
            return True
        value = value.get('result')
    if not value:
        return False
    return str(value).startswith('?')


@register.filter
def is_partial(value, with_upsolving=False):
    if with_upsolving and is_solved(value, with_upsolving=with_upsolving):
        return False
    if not value:
        return False
    return value.get('partial') or with_upsolving and is_partial(value.get('upsolving'))


def normalized_result(value):
    if not value:
        return value
    if str(value).startswith('+'):
        return '+'
    if str(value).startswith('-'):
        return '-'
    return as_number(value)


def is_improved_solution(curr, prev):
    curr_solved = is_solved(curr)
    prev_solved = is_solved(prev)
    if curr_solved != prev_solved:
        return curr_solved

    if not curr_solved:
        curr_upsolved = is_upsolved(curr)
        prev_upsolved = is_upsolved(prev)
        if curr_upsolved != prev_upsolved:
            return curr_upsolved

    curr_priority = curr.get('_solution_priority')
    prev_priority = prev.get('_solution_priority')
    if curr_priority is not None and prev_priority is not None and curr_priority != prev_priority:
        return curr_priority < prev_priority

    curr_result = normalized_result(curr.get('result'))
    prev_result = normalized_result(prev.get('result'))
    if type(curr_result) is not type(prev_result):
        return prev_result is None

    if curr_result is not None:
        if prev_result is None or prev_result < curr_result:
            return True
        if prev_result > curr_result or curr_solved:
            return False
        for f in ('id', 'submission_time'):
            if f in curr and f in prev and curr[f] > prev[f]:
                return True

    return False


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
        reti = toint(retf if retf % 1 < float_info.epsilon else valf)
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
def scoreformat(value, with_shorten=True):
    str_value = str(value)
    if not str_value or str_value[0] in ['+', '?']:
        return value
    format_value = floatformat(value, -2)
    str_value = format_value or str_value
    if with_shorten and len(str_value.split('.')[0]) > 7:
        try:
            new_str_value = f'{value:.3e}'.replace('+0', '+')
            if len(new_str_value) < len(str_value):
                ret = f'<span title="{value}" data-toggle="tooltip" data-placement="right">{new_str_value}</span>'
                return mark_safe(ret)
        except Exception:
            pass
    return format_value or value


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
    user = getattr(context['request'], 'user', None)
    if custom_countries and user and user.is_authenticated and country.code in custom_countries:
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
    if is_anonymous_user(user) or path == reverse('notification:messages'):
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
    return 1 / (1 + 10 ** ((a - b) / 400.0))


@register.simple_tag
def rating_from_probability(b, p, min_rating=0, max_rating=5000):
    if p <= 0:
        return max_rating
    if p >= 1:
        return min_rating
    a = math.log10(1 / p - 1) * 400 + b
    return min(max(a, min_rating), max_rating)


@register.simple_tag
def icon_to(value, default=None, icons=None, html_class=None):
    icons = icons or settings.FONTAWESOME_ICONS_
    if not default:
        default = value.title().replace('_', ' ')
    if value in icons:
        value = icons[value]
        inner = ''
        if isinstance(value, dict):
            if 'position' in value:
                inner += f' data-placement="{value["position"]}"'
            value, default, html_class = value['icon'], value.get('title', default), value.get('class', html_class)
        if default:
            inner += f' title="{default}" data-toggle="tooltip"'
        if html_class:
            inner += f' class="{html_class}"'
        ret = f'<span{inner}>{value}</span>'
        return mark_safe(ret)
    else:
        return default


@register.simple_tag(takes_context=True)
def list_data_field_to_select(context, field='list', nomultiply=False):
    CoderList = apps.get_model('true_coders', 'CoderList')
    request = context['request']
    coder = getattr(request.user, 'coder', None)
    list_uuids = [v for v in request.GET.getlist(field) if v]
    coder_lists, list_uuids = CoderList.filter_for_coder_and_uuids(coder=coder, uuids=list_uuids)
    options_values = {str(v.uuid): v.name for v in coder_lists}
    ret = {
        'values': list_uuids,
        'options': options_values,
        'noajax': True,
        'nogroupby': True,
        'nourl': True,
        'nomultiply': nomultiply,
    }
    return ret


def relative_url(url):
    urlinfo = urlparse(url)
    return urlinfo._replace(scheme='', netloc='').geturl()


def quote_url(url):
    return quote_plus(url)


@register.filter
def negative(value):
    return not bool(value)


@register.filter
def to_list(value):
    return list(value)


@register.filter
def media_size(path, size):
    ret = os.path.join(settings.MEDIA_URL, 'sizes', size, path)
    return ret


@register.filter
def allow_first(division_and_problem, stat):
    division, problem = division_and_problem
    if division != 'any' or not stat:
        return True
    first_ac_time = problem.get('first_ac', {}).get('time')
    return first_ac_time and first_ac_time == stat.get('time')


@register.filter
def sort_select_data(data):
    ret = {
        'noajax': True,
        'nogroupby': True,
        'nourl': True,
        'nomultiply': True,
        'state': {
            'values': ['asc', 'desc'],
            'icons': ['sort-asc', 'sort-desc'],
            'name': 'sort_order',
        },
    }
    if data.get('rev_order'):
        ret['state']['values'].reverse()
        ret['state']['icons'].reverse()

    ret.update(data)
    return ret


@register.filter
def simple_select_data(data):
    ret = {
        'noajax': True,
        'nogroupby': True,
        'nourl': True,
    }
    ret.update(data)
    return ret


@register.simple_tag
def submission_info_field(stat, field):
    counter = defaultdict(int)
    for submission_info in stat.get('_submission_infos', []):
        value = submission_info.get(field)
        if not value:
            continue
        counter[value] += 1
    ips = ''
    for v, k in sorted([(v, k) for k, v in counter.items()], reverse=True):
        ips += f'<div>{k} ({v})</div>'
    ret = f'<div title="{ips}" data-html="true" data-toggle="tooltip">'
    if len(counter) == 1:
        ret += 'IP'
    else:
        ret += f'IPs ({len(counter)})'
    ret += '</div>'
    return mark_safe(ret)


@register.filter
def has_update_statistics_permission(user, contest):
    ret = user.has_perm('ranking.update_statistics') or user.has_perm('update_statistics', contest.resource)
    if not ret and user.is_authenticated and contest.allow_updating_statistics_for_participants:
        ret = contest.statistics_set.filter(account__coders=user.coder).exists()
    return ret


@register.filter
def is_anonymous_user(user):
    return not user or user.username == settings.ANONYMOUS_USER_NAME


@register.filter
def format_to_significant_digits(number, digits):
    formatted = "{:.{precision}g}".format(number, precision=digits)
    if 'e' in formatted:
        formatted = str(float(formatted))
    return formatted


@register.filter
def is_ip_field(field):
    field = field.strip('_')
    return field == 'ips' or field.startswith('whois_')


@register.filter
def is_private_field(field):
    return is_ip_field(field)


@register.filter
def get_rating_predicition_field(field):
    for prefix in ('predicted', 'rating_prediction'):
        if field.startswith(prefix):
            field = field[len(prefix):]
            field = field.strip('_')
            if field:
                return field
    return False


@register.filter
def is_rating_change_field(field):
    return field in {'rating_change', 'ratingChange', 'predicted_rating_change', 'rating_prediction_rating_change'}


@register.filter
def is_new_rating_field(field):
    return field in {'new_rating', 'predicted_new_rating', 'rating_prediction_new_rating'}


@register.filter
def to_rating_change_field(field):
    return field.replace('new_rating', 'rating_change')


@register.simple_tag
def queryset_filter(qs, **kwargs):
    return qs.filter(**kwargs)


@register.simple_tag
def coder_account_filter(qs, account, row_number_field=None, operator=None):
    if account is None:
        return []
    ret = qs.filter(pk=account.pk).annotate(delete_on_duplicate=Value(True))
    if row_number_field:
        value = getattr(account, row_number_field)
        if value is not None:
            row_number = qs.filter(**{row_number_field + operator: value}).count() + 1
            ret = ret.annotate(row_number=Value(row_number))
    return ret


@register.filter
def not_empty(value):
    return value and value is not None and value != 'None'


@register.filter
def accounts_split(value):
    return re.split(r',(?=[^\s])', value)


@register.filter
def is_yes(value):
    return value and str(value).lower() in settings.YES_
