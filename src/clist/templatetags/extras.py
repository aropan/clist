import html
import itertools
import json
import math
import os
import re
from collections import OrderedDict, defaultdict
from collections.abc import Iterable
from copy import deepcopy
from datetime import datetime, timedelta
from numbers import Number
from sys import float_info
from urllib.parse import quote_plus, urlparse

import arrow
import pytz
import six
import yaml
from django import template
from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.db.models import Q, Value
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.template.base import Node
from django.template.defaultfilters import floatformat, slugify, stringfilter
from django.urls import NoReverseMatch, reverse
from django.utils.functional import keep_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe
from django.utils.timezone import now
from django_countries.fields import countries
from ipware import get_client_ip
from unidecode import unidecode

from utils.urlutils import absolute_url as utils_absolute_url

register = template.Library()


@register.filter
@stringfilter
def split(string, sep=" "):
    return string.split(sep)


@register.filter
def strip(string, val):
    return string.strip(val)


@register.filter
def get_item(data, key, default=None):
    if not data:
        return default

    if isinstance(data, (dict, defaultdict, OrderedDict)) and not isinstance(key, list):
        if key in data:
            return data.get(key)
    elif isinstance(data, (list, tuple)) and (key_as_number := as_number(key, force=True)) is not None:
        if -len(data) <= key_as_number < len(data):
            return data[key_as_number]
    elif isinstance(key, str) and hasattr(data, key):
        return getattr(data, key)

    if isinstance(key, str):
        for sep in ('.', '__'):
            if sep in key:
                key = key.split(sep)
                break

    if isinstance(key, (list, tuple)):
        for k in key:
            data = get_item(data, k)
            if data is None:
                return default
        return data

    return default


@register.filter
def get_item_from_list(data, key, default=None):
    if not data:
        return []
    return [get_item(item, key, default) for item in data]


@register.simple_tag
def set_item(data, key, value):
    data[key] = value
    return ''


@register.filter
def get_list(query_dict, key):
    return query_dict.getlist(key)


@register.filter
def get_nonempty_list(query_dict, key):
    return [v for v in query_dict.getlist(key) if v]


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
    if isinstance(delta, datetime):
        delta = (delta - now()).total_seconds()
    elif isinstance(delta, timedelta):
        delta = delta.total_seconds()
    if delta <= 0:
        return 'past'

    units = [
        (364 * 24 * 60 * 60, 'year'),
        (7 * 24 * 60 * 60, 'week'),
        (24 * 60 * 60, 'day'),
        (60 * 60, 'hour'),
        (60, 'minute'),
        (1, 'second'),
    ]

    rounded_delta = 0
    for seconds_per_unit, unit_name in units:
        if delta >= seconds_per_unit:
            n_significant -= 1
            val = round(delta / seconds_per_unit) if n_significant == 0 else delta // seconds_per_unit
            delta %= seconds_per_unit
            rounded_delta += val * seconds_per_unit
        elif rounded_delta:
            n_significant -= 1
        if n_significant == 0:
            break

    ret = []
    for seconds_per_unit, unit_name in units:
        if rounded_delta >= seconds_per_unit:
            val = rounded_delta // seconds_per_unit
            rounded_delta %= seconds_per_unit
            ret.append('%d %s%s' % (val, unit_name, 's' if val > 1 else ''))
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
    if h > 5:
        return "%d hours" % h
    if m + h > 0:
        return "%d:%02d:%02d" % (h, m, s)
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
        if token.email:
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
def md_url_text(value):
    return value.replace('[', '(').replace(']', ')')


@register.filter
def md_url(url):
    return utils_absolute_url(url.replace('(', '%28').replace(')', '%29'))


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


@register.filter
def asbool(value):
    return bool(value)


@register.simple_tag
def calc_mod_penalty(info, contest, solving, penalty):
    if not isinstance(penalty, (int, float)):
        return
    time = min((now() - contest.start_time).total_seconds(), contest.duration_in_secs) // 60
    return int(round(penalty - info['penalty'] + (info['solving'] - solving) * time))


@register.filter
def slug(value, sep=None):
    ret = slugify(unidecode(value)).strip('-')
    if sep:
        ret = ret.replace('-', sep)
    return ret


def is_problems_(contest_or_problems):
    return isinstance(contest_or_problems, (list, dict))


def get_problems_(contest_or_problems):
    if is_problems_(contest_or_problems):
        return contest_or_problems
    return contest_or_problems.info.get('problems', [])


def get_standings_divisions_order(contest_or_problems):
    problems = get_problems_(contest_or_problems)
    if 'division' in problems:
        divisions_order = list(problems.get('divisions_order', sorted(problems['division'].keys())))
    elif not is_problems_(contest_or_problems) and 'divisions_order' in contest_or_problems.info:
        divisions_order = contest_or_problems.info['divisions_order']
    else:
        divisions_order = []
    return divisions_order


@register.filter
def get_division_problems(contest_or_problems, info):
    problems = get_problems_(contest_or_problems)

    ret = []
    seen_keys = set()
    if 'division' in problems:
        division_addition = info.get('_division_addition')
        divisions = list(division_addition.keys()) if division_addition else []
        division = info.get('division')
        if division and division not in divisions:
            divisions = [division] + divisions
        for division in get_standings_divisions_order(contest_or_problems):
            if division not in divisions:
                divisions.append(division)
        for division in divisions:
            if division in problems['division']:
                for problem in problems['division'][division]:
                    problem_key = get_problem_key(problem)
                    if problem_key in seen_keys:
                        continue
                    seen_keys.add(problem_key)
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
    if isinstance(problem, dict) and '_header' in problem:
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


def get_problem_hash(contest, problem):
    has_code, code = get_problem_field(problem, 'code')
    if has_code:
        return code
    return (contest.id, get_problem_short(problem))


def get_problem_url(problem):
    has_url, url = get_problem_field(problem, 'url')
    return url if has_url else None


@register.simple_tag
def get_problem_solution(problem):
    ret = {}
    for contest in problem.contests.all():
        for statistic in contest.statistics_set.all():
            problems = get_division_problems(contest, statistic.addition)
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

                    res = {
                        'contest': contest,
                        'statistic': statistic,
                        'result': result,
                        'key': short,
                    }
                    if (
                        not ret or ret['result'] is None or
                        result is not None and is_improved_solution(result, ret['result'], with_upsolving=True)
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


def allowed_redirect(url):
    if not url_has_allowed_host_and_scheme(url, allowed_hosts=settings.ALLOWED_REDIRECT_HOSTS_):
        return HttpResponseForbidden('Invalid URL')
    return redirect(url)


def redirect_login(request):
    next_url = quote_url(request.get_full_path())
    redirect_url = reverse('auth:login') + f'?next={next_url}'
    if request.is_ajax():
        return JsonResponse({'redirect': redirect_url}, status=401)
    return allowed_redirect(redirect_url)


@register.simple_tag
def query_fields(request, *args, before='&', params: dict | None = None):
    updated = request.GET.copy()
    if args:
        for k in list(updated.keys()):
            if k not in args:
                updated.pop(k)
        if params:
            for k in args:
                if k not in updated and k in params:
                    updated[k] = params[k]

    ret = updated.urlencode()
    if ret:
        ret = before + ret
    return ret


@register.simple_tag
def get_countries():
    actual = []
    histrocal = []
    for c in countries:
        if not re.search(r'[a-zA-Z]', c.name) or c.code in settings.DISABLED_COUNTRIES:
            continue
        override_names = settings.COUNTRIES_OVERRIDE.get(c.code, {}).get('names')
        if override_names and override_names[0] != c.name:
            continue
        if c.code in settings.HISTORICAL_COUNTRIES:
            histrocal.append(c)
        else:
            actual.append(c)
    return actual + histrocal


def is_country_code(val):
    return val is not None and str(val).upper() in countries.countries


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
    try:
        return format_.format(**dict_values)
    except KeyError:
        return ''


@register.simple_tag
def format(format_, *args, **kwargs):
    return mark_safe(format_.format(*args, **kwargs))


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
def coder_color_class(resource, *values, value_name=None):
    rating, *_ = resource.get_rating_color(values, value_name=value_name)
    if not rating:
        return ''
    return f'coder-color coder-{rating["color"]}'


def circle_div(size, color, radius, width, fill, div_class=None, title=None):
    if isinstance(fill, (float, int)):
        v = fill * (size - 2 * width) + width
        fill = f'''
            <path
            clip-path="url(#rating-clip-{size})"
            d="M 0 {size} v-{round(v, 3)} h {size} 0 v{size} z"
            style="fill: {color}"
            />
        '''

    div_size = radius * 2 + width
    div_attrs = {}
    if div_class:
        div_attrs['class'] = div_class
    if title:
        div_attrs['title'] = title
        div_attrs['data-html'] = 'true'
        div_attrs['data-toggle'] = 'tooltip'
    div_attrs = ' '.join(f'{k}="{v}"' for k, v in div_attrs.items())
    return mark_safe(
        f'''
        <div
            {div_attrs}
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


@register.simple_tag
def medal_percentage(medal, percent, info=None, size=16):
    radius = size // 2
    width = size // 10
    title = f'{medal.title()}'
    if info:
        title += f'<br/>{info}'
    title += f'<br/>{percent * 100:.2f}%'
    return circle_div(size, 'inherit', radius, width, percent, title=title, div_class=f'{medal}-medal-percentage')


@register.simple_tag
def coder_color_circle(resource, *values, size=16, value_name=None, **kwargs):
    Account = apps.get_model('ranking', 'Account')
    cleaned_values = [a.info if isinstance(a, Account) else a for a in values]
    rating, value = resource.get_rating_color(cleaned_values, value_name=value_name)
    if not rating:
        return ''
    color = rating['hex_rgb']
    radius = size // 2
    width = size // 10
    reverse_percent = resource.info.get('ratings', {}).get('reverse_circle_percent')

    title = f'{value}'
    has_percent = ('prev' if reverse_percent else 'next') in rating
    if has_percent:
        prv = max(rating.get('prev', rating['low']), 0)
        nxt = rating.get('next', value)
        percent = (value - prv) / (nxt - prv)
        if reverse_percent:
            percent = 1 - percent
        fill = percent
        if 'next' in rating:
            title += f' ({percent * 100:.1f}%)'
    if not has_percent or rating.get('target'):
        fill = f'<circle cx="{radius}" cy="{radius}" r="{size // 5}" style="fill: {color}"></circle>'
    if 'name' in rating:
        title += f'<br/>{rating["name"]}'
    if len(values) == 1 and isinstance(values[0], Account):
        resource_rank = values[0].resource_rank
        if resource_rank:
            total_rank = resource.n_rating_accounts
            percent = resource_rank * 100 / total_rank
            percent = format_to_significant_digits(percent, 2)
            title += f'<br/>#{resource_rank} of {total_rank} ({percent}%)'
    return circle_div(size, color, radius, width, fill, title=title, div_class='coder-circle')


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
def subtract(value, arg):
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
    if arg is None:
        return value
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
        return mark_safe(f'<i class="fas fa-{"check" if value else "times"}"></i>')
    if isinstance(value, float):
        value_str = str(value)
        if '.' in value_str:
            length = len(value_str.split('.')[-1])
            if length > 3:
                return mark_safe(f'<span title="{value}" data-toggle="tooltip">{value:.3f}</span>')
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
    if isinstance(value, dict):
        if result_verdict := value.get('result_verdict'):
            return result_verdict == 'accepted'
        if with_upsolving and 'upsolving' in value and is_solved(value['upsolving']):
            return True
        if value.get('partial'):
            return False
        if value.get('binary') is True:
            return True
        value = value.get('result')
    if value is None:
        return False
    if isinstance(value, str):
        if value.startswith('+'):
            return True
        try:
            value = float(value)
        except ValueError:
            return False
    return value > 0


@register.filter
def is_reject(value, with_upsolving=False):
    if isinstance(value, dict):
        if result_verdict := value.get('result_verdict'):
            return result_verdict == 'rejected'
        if with_upsolving and 'upsolving' in value and is_reject(value['upsolving']):
            return True
        if value.get('binary') is False:
            return True
        value = value.get('result')
    if value is None:
        return False
    if isinstance(value, str):
        if value.startswith('-'):
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
    return isinstance(value, dict) and 'upsolving' in value and is_solved(value['upsolving'])


@register.filter
def is_hidden(value, with_upsolving=False):
    if isinstance(value, dict):
        if result_verdict := value.get('result_verdict'):
            return result_verdict == 'hidden'
        if with_upsolving and 'upsolving' in value and is_hidden(value['upsolving']):
            return True
        value = value.get('result')
    return isinstance(value, str) and value.startswith('?')


@register.filter
def is_partial(value, with_upsolving=False):
    if is_solved(value, with_upsolving=with_upsolving):
        return False
    if is_reject(value, with_upsolving=with_upsolving):
        return False
    if not value or not isinstance(value, dict):
        return False
    return value.get('partial') or with_upsolving and 'upsolving' in value and is_partial(value['upsolving'])


def is_scoring_result(value):
    if isinstance(value, dict):
        if 'upsolving' in value and is_scoring_result(value['upsolving']):
            return True
        value = value.get('result')
    value_str = str(value)
    return value_str and value_str[0].isdigit()


def normalized_result(value):
    if not value:
        return value
    if str(value).startswith('+'):
        return '+'
    if str(value).startswith('-'):
        return '-'
    if str(value).startswith('?'):
        return '?'
    return as_number(value)


def get_result_score(value):
    if isinstance(value, dict):
        value = value.get('result')
    value_str = str(value)
    if value_str.startswith('+'):
        return 1
    if value_str.startswith('-'):
        return 0
    if value_str.startswith('?'):
        return 0
    return as_number(value, default=0)


def place_as_n_place_field(place):
    if isinstance(place, str):
        place = as_number(place, force=True)
    if place and 1 <= place <= 10:
        ret = {1: 'first', 2: 'second', 3: 'third'}.get(place, 'top_ten')
        return f'n_{ret}_places'


def medal_as_n_medal_fields(medal, place: int | None = None):
    medal = medal.lower()
    if medal in ('gold', 'silver', 'bronze'):
        ret = [f'n_{medal}', 'n_medals']
    else:
        ret = ['n_other_medals']
    if medal and place == 1:
        ret.append('n_win')
    return ret


@register.simple_tag
def get_statistic_stats(addition, solving=None, with_n_medal_field=False, with_n_place_field=False):
    ret = {}
    problems = addition.get('problems', {})
    n_upsolving = 0
    upsolving = 0
    n_solved = 0
    n_upsolved = 0
    n_first_ac = 0
    for k, v in problems.items():
        if is_solved(v):
            n_solved += 1
        elif is_upsolved(v):
            n_upsolved += 1
        if v.get('first_ac'):
            n_first_ac += 1
        if (u := v.get('upsolving')):
            u_score = get_result_score(u)
            v_score = get_result_score(v)
            upsolving += max(0, u_score - v_score)
            n_upsolving += 1
    if n_upsolving:
        ret['upsolving'] = upsolving
        ret['n_upsolved'] = n_upsolved
    else:
        ret.pop('upsolving', None)
        ret.pop('n_upsolved', None)
    ret['solving'] = as_number(solving if solving is not None else addition.get('solving'), default=0)
    ret['total_solving'] = ret.get('solving', 0) + ret.get('upsolving', 0)
    ret['n_solved'] = n_solved
    ret['n_total_solved'] = n_solved + n_upsolved
    ret['n_first_ac'] = n_first_ac

    if with_n_medal_field and (medal := addition.get('medal')):
        for field in medal_as_n_medal_fields(medal):
            ret[field] = 1
    if with_n_place_field and (n_place_field := place_as_n_place_field(with_n_place_field)):
        ret[n_place_field] = 1
        ret['n_places'] = 1
    return ret


def is_improved_solution(curr, prev, with_upsolving=False):
    curr_solved = is_solved(curr)
    prev_solved = is_solved(prev)
    if curr_solved != prev_solved:
        return curr_solved

    if with_upsolving and not curr_solved:
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
    if isinstance(curr_result, Number) and isinstance(prev_result, Number) and curr_result != prev_result:
        return curr_result > prev_result

    for f in ('id', 'submission_time'):
        curr_in = f in curr
        prev_in = f in prev
        if curr_in != prev_in:
            return curr_in
        if curr_in and prev_in and curr[f] > prev[f]:
            return True

    return False


def time_compare_value(val):
    if isinstance(val, Number):
        val = [val]
    else:
        val = list(map(int, val.split(':')))
    return len(val), val


def solution_time_compare(lhs, rhs):
    for k in 'time_in_seconds', 'time':
        if k not in lhs or k not in rhs:
            continue
        l_val = time_compare_value(lhs[k])
        r_val = time_compare_value(rhs[k])
        if l_val != r_val:
            return -1 if l_val < r_val else 1
    return 0


@register.filter
def timestamp_to_datetime(value):
    try:
        if isinstance(value, str):
            value = float(value)
        return datetime.fromtimestamp(value, tz=pytz.utc)
    except Exception:
        return None


@register.filter
def has_passed_since_timestamp(value):
    return now().timestamp() - value


@register.filter
def highlight_class(lang):
    lang = lang.lower()
    lang = re.sub(r'\s*\(.*\)$', '', lang)
    lang = re.sub(r'\s*[.0-9]+', '', lang)
    lang = re.sub(r'([a-z])\+\+', r'\1pp', lang)
    lang = re.sub(r'([a-z])\#', r'\1sharp', lang)
    lang = re.sub(' ', '', lang)
    return lang


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
def as_number(value, force=False, default=None):
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
    if default is not None:
        return default
    if force:
        return None
    return value


def _title_field(value):
    value = re.sub('([A-Z]+)', r'_\1', value)
    values = re.split('_+', value)
    values = [v.title() for v in values]
    return values


@register.filter
def title_field(value):
    return ' '.join(_title_field(value))


@register.filter
def title_field_div(value, split=False):
    return mark_safe(''.join([f'<div>{f}</div>' for f in _title_field(value.strip('_'))]))


def normalize_field(k):
    if k[0].isalpha() and not re.match('^[A-Z]+([0-9]+)?$', k):
        k = k[0].upper() + k[1:]
        k = '_'.join(map(str.lower, re.findall('([A-ZА-Я]+[^A-ZА-Я]+|[A-ZА-Я]+$)', k)))
        k = re.sub('_+', '_', k)
    return k


@register.filter
def scoreformat(value, with_shorten=True, precision=-2):
    str_value = str(value)
    if not str_value or str_value[0] in ['+', '?']:
        return value
    format_value = floatformat(value, precision)
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
def scorefixedformat(value, precision=-2, with_shorten=True):
    return scoreformat(value, with_shorten=with_shorten, precision=precision)


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
def ifnone(val, ret):
    return ret if val is None else val


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


@register.filter
def allow_custom_countries(request, country):
    if country.code in settings.FILTER_CUSTOM_COUNTRIES_:
        geo_country_code = get_geo_country_code(request)
        if geo_country_code in settings.FILTER_CUSTOM_COUNTRIES_[country.code]:
            return False
    return True


@register.filter
def get_geo_country_code(request):
    client_ip, routable = get_client_ip(request)
    if not client_ip:
        return
    return settings.GEOIP.country_code(client_ip)


def get_custom_country(request, country, custom_countries):
    user = getattr(request, 'user', None)
    if not custom_countries or country.code not in custom_countries:
        return
    if not user or not user.is_authenticated:
        return
    if not allow_custom_countries(request, country):
        return
    return custom_countries[country.code]


def get_country_from(context, country, custom_countries):
    country_code = get_custom_country(context['request'], country, custom_countries) or country.code
    setattr(country, 'flag_code', country_code)
    return country


@register.simple_tag(takes_context=True)
def get_country_from_account(context, account):
    return get_country_from(context, account.country, account.info.get('custom_countries_'))


@register.simple_tag(takes_context=True)
def get_country_from_coder(context, coder):
    return get_country_from(context, coder.country, coder.settings.get('custom_countries'))


@register.simple_tag
def get_country_from_members(accounts, members):
    counter = defaultdict(int)
    for member in members:
        if not member or 'account' not in member:
            continue
        account = accounts.get(member['account'])
        if account is None or not account.country:
            continue
        counter[account.country.code] += 1
    if not counter:
        return
    country = max(counter, key=counter.get)
    if counter[country] <= len(members) / 2:
        return
    return country


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
def trim_to(value, length, raw_text=False):
    if not length or len(value) - 1 < length:
        return value

    half = length // 2
    separator = '…'

    prefix = half
    while prefix > 0 and value[prefix - 1].isspace():
        prefix -= 1
    suffix = len(value) - half
    while suffix < len(value) and value[suffix].isspace():
        suffix += 1
    prefix, middle, suffix = value[:prefix], value[prefix:suffix], value[suffix:]

    if raw_text:
        return f'{prefix}{separator}{suffix}'

    prefix, middle, suffix = map(html.escape, (prefix, middle, suffix))
    separator = f'<span class="expandable-text">{middle}</span><span class="expandable-click" onclick="return expand_trimmed_text(event, this)">{separator}</span>'  # noqa: E501
    ret = f'<span title="{html.escape(value)}" data-toggle="tooltip">{prefix}{separator}{suffix}</span>'
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
def icon_to(value, default=None, icons=None, html_class=None, inner='', **kwargs):
    icons = icons or settings.FONTAWESOME_ICONS_
    if default is None:
        default = value.title().replace('_', ' ')
    if value in icons:
        value = icons[value]
        params = kwargs
        if isinstance(value, dict):
            params = deepcopy(value)
            if kwargs:
                params.update(kwargs)

        if 'position' in kwargs:
            inner += f' data-placement="{kwargs["position"]}"'
        if 'icon' in params:
            value = params['icon']
        if 'class' in params:
            html_class = params['class']
        if 'title' in params:
            default = params['title']
    else:
        value = title_field(value)
    if default:
        inner += f' title="{default}" data-toggle="tooltip"'
    if html_class:
        inner += f' class="{html_class}"'
    ret = f'<span{inner}>{value}</span>'
    return mark_safe(ret)


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


@register.simple_tag(takes_context=True)
def chat_data_field_to_select(context, field='chat', nomultiply=False, owned=True):
    request = context['request']
    coder = getattr(request.user, 'coder', None)
    options_values = {}
    if coder:
        chats = coder.chat_set.all() if owned else coder.chats.all()
        options_values = {c.chat_id: c.title for c in chats}
    ret = {
        'values': [v for v in request.GET.getlist(field) if v and v in options_values],
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
def url_with_params_separator(url):
    return f'{url}{"&" if "?" in url else "?"}'


@register.filter
def negative(value):
    return not bool(value)


@register.filter
def to_list(value):
    return list(value)


@register.filter
def prepend(array, value):
    array.insert(0, value)
    return array


@register.filter
def media_size(path, size):
    ret = os.path.join(settings.MEDIA_URL, 'sizes', size, path)
    return ret


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
    if data is None or data == '':
        return
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
    return field in ['ips', 'n_ips'] or field.startswith('whois_')


@register.filter
def is_private_field(field):
    return is_ip_field(field)


@register.filter
def get_rating_predicition_field(field):
    for prefix in ('predicted_', 'rating_prediction_'):
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
def normalize_rating_prediction_field(field):
    return field.replace('rating_prediction__', 'rating_prediction_')


@register.filter
def to_rating_change_field(field):
    return field.replace('new_rating', 'rating_change')


@register.filter
def is_rating_prediction_field(field):
    return field and field.startswith('rating_prediction_')


@register.simple_tag
def rating_change_template(value):
    if not isinstance(value, (float, int)):
        value = as_number(value, force=True)
    if not value:
        span_class = 'rating-change-same'
    elif value > 0:
        span_class = 'rating-change-up'
    else:
        span_class = 'rating-change-down'
    ret = f'<span class="rating-change {span_class}">{icon_to(span_class)}{abs(value)}</span>'
    return mark_safe(ret)


@register.simple_tag
def queryset_filter(qs, **kwargs):
    return qs.filter(**kwargs)


@register.simple_tag
def coder_account_filter(queryset, entity, row_number_field=None, operator=None):
    if not entity:
        return []
    ret = queryset.filter(pk=entity.pk).annotate(delete_on_duplicate=Value(True))
    if row_number_field:
        fields = row_number_field.split(',')
        if all(hasattr(entity, field) for field in fields):
            values = [getattr(entity, field) for field in fields]
        else:
            values = queryset.filter(pk=entity.pk).values_list(fields, flat=True).first()

        if any(value is not None for value in values):
            combined_filter = Q()
            fields_values = list(zip(fields, values))
            for idx, (field, value) in enumerate(fields_values):
                if value is None:
                    condition = Q(**{f'{field}__isnull': False})
                else:
                    condition = Q(**{field + operator: value})
                for field, value in fields_values[:idx]:
                    condition &= Q(**{field: value})
                combined_filter |= condition
            row_number = queryset.filter(combined_filter).count() + 1
            ret = ret.annotate(row_number=Value(row_number))
    else:
        ret = ret.annotate(row_number=Value('—'))
    return ret


@register.filter
def not_empty(value):
    return value and value is not None and value != 'None'


@register.filter
def accounts_split(value):
    return re.split(r',(?=[^\s])', value)


@register.filter
def is_yes(value):
    return str(value).lower() in settings.YES_


@register.filter
def is_optional_yes(value):
    if value is None:
        return None
    return is_yes(value)


@register.filter
def get_admin_url(obj):
    if obj is None:
        return
    content_type = ContentType.objects.get_for_model(obj.__class__)
    try:
        return reverse("admin:%s_%s_change" % (content_type.app_label, content_type.model), args=(obj.pk,))
    except NoReverseMatch:
        return


@register.simple_tag
def admin_url(obj):
    url = get_admin_url(obj)
    icon = icon_to('database', '')
    return mark_safe(f'<a href="{url}" class="database-link invisible" target="_blank" rel="noopener">{icon}</a>')


@register.simple_tag
def stat_has_failed_verdict(stat):
    return not is_solved(stat) and stat.get('verdict') and not stat.get('binary') and not stat.get('icon')


@register.simple_tag
def stat_verdict_class(stat, upsolving=False):
    if is_solved(stat):
        return 'upsolved' if upsolving else 'acc'
    if is_upsolved(stat):
        return 'upsolved'
    if is_hidden(stat):
        return 'hid'
    if is_reject(stat):
        return 'rej'
    if is_partial(stat):
        return 'par'
    return ''


@register.simple_tag
def search_linked_coder(request, account):
    name_instead_key = get_item(account, 'resource.info.standings.name_instead_key')
    value = account.name if name_instead_key else account.key

    search = request.GET.get('search')
    if search:
        if value in search.split(' || '):
            return False
        search = f'{search} || {value}'
    else:
        search = value

    return search


@register.simple_tag(takes_context=True)
def time_ago(context, time):
    if not time:
        return
    title = format_time(timezone(time, context['timezone']), context['timeformat'])
    value = naturaltime(timezone(time, context['timezone']))
    return mark_safe(f'<span title="{title}" data-placement="top" data-toggle="tooltip">{value}</span>')


@register.filter
def strip_milliseconds(value):
    return re.sub(r'\.[0-9]+$', '', str(value))


@register.simple_tag
def get_result_class(result):
    if is_solved(result, True):
        return 'success'
    if is_hidden(result, True):
        return 'warning'
    if is_reject(result, True):
        return 'danger'
    if is_partial(result, True):
        return 'info'
    return ''


@register.simple_tag
def tests_distribution(tests):
    counter = {}
    for test in tests:
        test_counter = counter.setdefault(test.verdict, {})
        test_counter.setdefault('total', 0)
        test_counter['total'] += 1
        if test.test_number is not None:
            test_counter.setdefault('tests', []).append(test.test_number)
    ret = ''
    for verdict, test_counter in sorted(counter.items(), key=lambda x: -x[1]['total']):
        title = ''
        if 'tests' in test_counter:
            start = None
            last = None
            tests = []
            for t in sorted(test_counter['tests']):
                if not last or last + 1 != t:
                    if start:
                        tests.append(f'{start}-{last}' if start != last else str(start))
                    start = t
                last = t
            if last:
                tests.append(f'{start}-{last}' if start != last else str(start))
            if tests:
                title = f' data-toggle="tooltip" title="Tests: {", ".join(tests)}"'

        badge_class = 'success' if verdict.solved else 'danger'
        ret += (
            f'''<span class="testing-verdict-result"{title}>'''
            f'''<span class="badge progress-bar-{badge_class}">{verdict.id}</span>'''
            f'''&times;<span>{test_counter['total']}</span>'''
            f'''</span>'''
        )
    return mark_safe(ret)


@register.simple_tag
def contest_submissions_to_timeline_json(submissions):
    ret = {}
    for submission in submissions.order_by('contest_time'):
        d = ret.setdefault(str(submission.statistic_id), {})
        d = d.setdefault(submission.problem_index, [])
        d.append([
            int(submission.contest_time.total_seconds()),
            submission.current_result,
            submission.current_attempt,
        ])
    return mark_safe(json.dumps(ret))


@register.simple_tag(takes_context=True)
def value_with_select(context, field, value, default=None):
    if value is None:
        return default
    values = (f for f in context['request'].GET.getlist(field) if f)
    if any(values):
        return value
    url = url_transform(context['request'], field, value)
    return mark_safe(f'<a href="{url}">{value}</a>')


@register.simple_tag
def filtered_admin_url(url, field_selects):
    params = []
    for field_select in field_selects:
        field = field_select['name']
        values = field_select['values']
        if not values:
            continue
        if len(values) > 1:
            params.append(f'{field}__in={",".join(values)}')
        else:
            params.append(f'{field}={values[0]}')
    if params:
        url += '?' + '&'.join(params)
    return url


@register.filter
def camel_to_snake(value):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', value).lower()


@register.simple_tag
def label_tag(label, status=None):
    label = html.escape(label)
    status = status or 'info'
    return mark_safe(f'<span class="label label-sm alert-{status} label-tag">{label}</span>')


@register.filter
def is_major_kind(resource, value):
    return resource.is_major_kind(value)


@register.simple_tag
def profile_url(account, resource=None, inner=None, html_class=None):
    resource = resource or account.resource
    return_inner = ''
    if not resource.profile_url:
        return return_inner
    if account.info.get('_no_profile_url'):
        return return_inner
    url = format_dict(resource.profile_url, account.dict_with_info())
    if not url:
        return return_inner
    if inner and inner.startswith('icon_to:'):
        _, inner = inner.split(':', 1)
        inner = icon_to(inner)
    else:
        inner = inner or icon_to('profile')
    html_class = f'class="{html_class}"' if html_class else ''
    return mark_safe(f'<a href="{url}" {html_class} target="_blank" rel="noopener">{inner}</a>')


@register.simple_tag
def create_dict(**kwargs):
    return kwargs


@register.simple_tag
def create_nonempty_dict(**kwargs):
    return {k: v for k, v in kwargs.items() if v is not None and v != ''}


@register.simple_tag
def create_list(*args):
    return list(args)


@register.filter
def ne(value, arg):
    return value != arg


@register.simple_tag(takes_context=True)
def absolute_url(context, viewname, *args, **kwargs):
    return context['request'].build_absolute_uri(reverse(viewname, args=args, kwargs=kwargs))


@register.filter
def get_id(value):
    return id(value)


@register.filter
def get_more_fields(more_fields):
    for field in more_fields:
        if '=' in field:
            continue
        yield field


@register.filter
def capitalize_field(value):
    return title_field(value).capitalize()


@register.simple_tag(takes_context=True)
def field_to_select_values(context):
    data = context['data']
    if data.get('options') is not None:
        field_name = data.get('field_name', context['field'])
        values = context['request'].get_filtered_list(field_name, options=data['options'])
        if values:
            return values
    if data.get('data'):
        if (values := [d['id'] for d in data['data'] if d.get('selected')]):
            return values
    if 'values' in data:
        return data['values']
    if 'value' in data:
        return [data['value']]
    return None


@register.simple_tag(takes_context=True)
def field_to_select_collapse(context):
    if 'collapse' in context['data']:
        return context['data']['collapse']
    if context['values'] or context.get('noinputgroup'):
        return False
    if (
        not context['data'].get('nogroupby')
        and context['groupby'] == context['field']
    ):
        return False
    return True


@register.simple_tag(takes_context=True)
def field_to_select_id(context, value):
    if 'value_id' in context['data']:
        return get_item(value, context['data']['value_id'])
    return value


@register.simple_tag(takes_context=True)
def field_to_select_option(context, value):
    if isinstance(options := context['data'].get('options'), dict):
        value = options.get(value, value)
    if 'value_option' in context['data']:
        return get_item(value, context['data']['value_option'])
    return value


@register.filter
def ifor(value, arg):
    return value or arg


@register.filter
def ifand(value, arg):
    return value and arg


@register.filter
def html_unescape(value):
    value = html.unescape(value)
    value = value.replace('\xa0', ' ').strip()
    return value


@register.filter
def deep_copy(value):
    return deepcopy(value)


@register.filter
def update_dict(value, arg):
    value.update(arg)
    return value


@register.simple_tag
def img_resource_icon(resource, size, with_href=False):
    pow2_size = max(32, 2 ** math.ceil(math.log2(size) + 1))
    url = media_size(resource.icon, f'{pow2_size}x{pow2_size}')
    html = f'<img src="{url}" width="{size}" height="{size}" alt="{resource.host}">'
    if with_href:
        attrs = f'href="{resource.href()}" title="{resource.host}"'
        html = f'<a {attrs} target="_blank" rel="noopener noreferrer" data-toggle="tooltip">{html}</a>'
    return mark_safe(html)


def allow_first(division, problem, stat):
    if division != 'any' or not stat:
        return True
    first_ac_time = problem.get('first_ac', {}).get('time')
    return first_ac_time and first_ac_time == stat.get('time')


def get_default_dict(data, default):
    return defaultdict(lambda: default, data or {})


@register.simple_tag(takes_context=True)
def standings_statistic_problem_attributes(context):
    contest = context['contest']
    statistic = context['statistic']
    my_stat = getattr(statistic, 'my_stat', None)
    problem = get_default_dict(context['problem'], '')
    key = get_problem_short(problem)
    full_score = problem['full_score']
    result = get_default_dict(context['stat'], '')
    division = context.get('division')
    with_first = allow_first(division, problem, result)

    class_attr = 'problem-cell'
    result_class = ''
    if result:
        class_attr += ' problem-cell-stat'
        if '_class' in result:
            result_class = f' {result["_class"]}'
        elif with_first and result['first_ac_of_all']:
            result_class = ' first-ac-of-all'
        elif with_first and result['first_ac']:
            result_class = ' first-ac'
        elif result['max_score']:
            result_class = ' max-score'
        class_attr += f' {result_class}'

        if key in context.get('hide_problems', []) and not my_stat:
            class_attr += ' blurred-text'
        if my_stat and context.get('with_solution'):
            class_attr += ' drop-zone'

    attrs = f'class="{class_attr}"'
    if result:
        full_score_instead_result = full_score and is_solved(result) and not contest.is_stage()
        score = f'{full_score}' if full_score_instead_result else f'{result["result"]}'
        attrs += f' data-score="{score}"'
        attrs += f' data-result="{result["result"]}"'
        attrs += f' data-penalty="{result["time"]}"'

        problem_sec = problem['time_in_seconds']
        result_sec = result['time_in_seconds']
        penalty_in_seconds = problem_sec if problem_sec and contest.is_stage() else result_sec
        attrs += f' data-penalty-in-seconds="{penalty_in_seconds}"'
        attrs += f' data-more-penalty="{result["penalty"]}"'
        attrs += f' data-class="{result_class}"'

        if getattr(statistic, 'virtual_start', None):
            attrs += ' data-active-switcher="true"'
    attrs += f' data-problem-key="{key}"'
    attrs += f' data-problem-full-score="{full_score}"'

    return mark_safe(attrs)


def format_optional(value, prefix='', suffix=''):
    return f"{prefix}{html.escape(str(value))}{suffix}" if value is not None and value != '' else ''


def format_score(value):
    return scoreformat(value)


def format_verdict(verdict, test):
    return f"{html.escape(str(verdict))}{format_optional(test, '(', ')')}"


def format_time_display(time, penalty, time_rank, attempt):
    ret = ''.join((
        html.escape(str(time)),
        format_optional(penalty, '+'),
        format_optional(time_rank, ' (', ')'),
        format_optional(attempt, ' (', ')'),
    ))
    return ret


def format_status(status, status_tag, is_small):
    escaped_status = html.escape(str(status))
    if status_tag and is_small:
        safe_tag = html.escape(str(status_tag))
        return f"<{safe_tag}>{escaped_status}</{safe_tag}>"
    return escaped_status


def format_upsolving_icon(upsolving_stat):
    icon_class = "check" if is_solved(upsolving_stat) else "times"
    return f'<i class="fas fa-{icon_class}"></i>'


@register.simple_tag(takes_context=True)
def standings_statistic_problem_detail(context, small, stat=None):
    upsolving_small = small
    stat = get_default_dict(stat or context['stat'], '')
    result_html = []
    has_failed_verdict = stat_has_failed_verdict(stat)

    if small:
        result_html.append('<small class="text-muted">')
    else:
        subscores = stat['subscores']
        if subscores:
            result_html.append('<div>')
            for i, subscore in enumerate(subscores):
                if not isinstance(subscore, dict):
                    continue
                if i > 0:
                    result_html.append('+')
                subscore_cls = ''
                if subscore.get('verdict'):
                    subscore_cls = ' class="acc"' if subscore.get('result') else ' class="rej"'
                result_html.append(f'<span{subscore_cls}>{html.escape(str(subscore.get("status", "")))}</span>')
            result_html.append('</div>')
        if has_failed_verdict:
            result_html.append(f'<div class="rej">{format_verdict(stat["verdict"], stat["test"])}</div>')
        if result_rank := stat['result_rank']:
            result_html.append(f'<div>Rank: {html.escape(str(result_rank))}</div>')

    result_html.append('<div class="nowrap">')

    stat_status = stat['status']
    stat_time = stat['time']
    stat_result = stat['result']
    stat_extra_score = stat['extra_score']
    stat_penalty = stat['penalty']
    stat_time_rank = stat['time_rank']
    stat_attempt = stat['attempt']
    stat_status_tag = stat['status_tag']
    stat_delta_time = stat['delta_time']
    stat_virtual_start_ts = stat['virtual_start_ts']
    stat_best_score = stat['best_score']
    stat_language = stat['language']
    stat_upsolving = stat['upsolving']

    without_score = not stat_result and not stat_extra_score
    status_and_time_cond = (stat_status and stat_time) and (without_score and context.get('with_detail') or not small)
    status_cond = stat_status and (not stat_time or is_reject(stat))
    delta_time_cond = small and stat_delta_time and stat_time
    time_cond = stat_time
    failed_verdict_cond = has_failed_verdict and small
    virtual_start_cond = stat_virtual_start_ts
    best_score_cond = stat_best_score and stat_best_score

    if status_and_time_cond:
        upsolving_small = None
        result_html.append(f'<div>{format_status(stat_status, stat_status_tag, small)}</div>')
        result_html.append(f'<div>{format_time_display(stat_time, stat_penalty, stat_time_rank, stat_attempt)}</div>')
    elif status_cond:
        result_html.append(f'{format_status(stat_status, stat_status_tag, small)}')
    elif delta_time_cond:
        result_html.append('<a href="" onclick="toggle_hidden(this, event)" data-class="detail-alternative-time">')
        result_html.append(f'<span class="detail-alternative-time hidden">{html.escape(str(stat_delta_time))}</span>')
        result_html.append(f'<span class="detail-alternative-time">{html.escape(str(stat_time))}</span>')
        result_html.append('</a>')
    elif time_cond:
        result_html.append(f'<span>{format_time_display(stat_time, stat_penalty, stat_time_rank, stat_attempt)}</span>')
    elif failed_verdict_cond:
        result_html.append(f'<span>{format_verdict(stat["verdict"], stat["test"])}</span>')
    elif virtual_start_cond:
        time_passed = has_passed_since_timestamp(stat_virtual_start_ts)
        countdown_str = countdown(time_passed)
        timestamp_up = html.escape(str(stat_virtual_start_ts))
        result_html.append(f'<span class="countdown" data-timestamp-up="{timestamp_up}">{countdown_str}</span>')
    elif best_score_cond:
        result_html.append(f'<small class="text-muted">{format_score(stat_best_score)}</small>')
    else:
        upsolving_small = False

    if upsolving_small is not None and isinstance(stat_upsolving, dict):
        tag = "span" if small else "div"
        result_html.append(f'<{tag}')
        if upsolving_small:
            result_html.append(f'class="{stat_verdict_class(stat_upsolving, True)}"')
            result_html.append('data-toggle="tooltip"')
            result_html.append('data-placement="top"')
            result_html.append('data-html="true"')
            result_html.append("title='Upsolving<br/>")
        else:
            result_html.append('>')

        if stat_upsolving.get('binary') is not None:
            result_html.append(format_upsolving_icon(stat_upsolving))
        elif (upsolving_result := stat_upsolving.get('result')) is not None:
            result_html.append(f'{format_score(upsolving_result)}')
        if not is_solved(stat_upsolving) and (upsolving_verdict := stat_upsolving.get('verdict')):
            result_html.append(f' {format_verdict(upsolving_verdict, stat_upsolving.get("test"))}')

        if upsolving_small:
            result_html.append("'>&#65290;")
        result_html.append(f'</{tag}>')

    if not small and stat_delta_time:
        result_html.append(f'<div>{html.escape(str(stat_delta_time))}</div>')
    if not small and stat_language:
        result_html.append(f'<div class="language">{html.escape(str(stat_language))}</div>')

    result_html.append('</div>')

    if small:
        result_html.append('</small>')

    return mark_safe(" ".join(result_html))


@register.simple_tag(takes_context=True)
def standings_statistic_problem(context):
    stat = get_default_dict(context['stat'], '')
    if not stat:
        return mark_safe('<div>&#183;</div>')

    request = context['request']
    statistic = context['statistic']
    key = context['key']
    my_stat = getattr(statistic, 'my_stat', None)
    perms = context.get('perms')
    contest = context.get('contest')
    with_detail = context.get('with_detail')
    with_admin_url = context.get('with_admin_url')
    standings_options = context.get('standings_options')
    fields_to_select = context.get('fields_to_select')
    with_result_name = context.get('with_result_name')
    languages = get_list(request.GET, 'languages')

    is_upsolving = context.get('with_upsolving') and not is_solved(stat) and is_upsolved(stat)
    if is_upsolving:
        stat = get_default_dict(stat['upsolving'], '')

    html_parts = []

    html_parts.append('<div class="nowrap">')

    div_classes = ["inline", "text-nowrap"]
    if languages and stat['language'] not in languages and 'any' not in languages:
        div_classes.append("text-muted")
    elif stat.get('binary') is None and with_detail and stat.get('subscores'):
        pass
    elif is_solved(stat):
        div_classes.append("text-muted small" if is_upsolving else "acc")
    elif is_hidden(stat):
        div_classes.append("hid")
    elif is_reject(stat):
        div_classes.append("rej")
    elif is_partial(stat):
        div_classes.append("par")

    if statistic and getattr(statistic, 'virtual_start', None):
        div_classes.append("vir")

    html_parts.append(f'<div class="{" ".join(div_classes)}"')
    if not with_detail:
        if stat.get('status') or stat.get('time') or stat.get('upsolving') or stat.get('verdict') or stat.get('language'):
            tooltip_title = standings_statistic_problem_detail(context, small=False, stat=stat)
            tooltip_attrs = f' title=\'{tooltip_title}\' data-toggle="tooltip" data-placement="top" data-html="true"'
            html_parts.append(tooltip_attrs)
    html_parts.append('>')

    has_alternative_result = context.get('has_alternative_result')
    if has_alternative_result :
        alternative_result = get_item(stat, standings_options.get('alternative_result_field'), '&#183;')
        html_parts.append('<a href="" onclick="toggle_hidden(this, event)" data-class="detail-alternative-result">')
        html_parts.append(f'<span class="detail-alternative-result hidden">{html.escape(str(alternative_result))}</span>')
        html_parts.append('<span class="detail-alternative-result">')

    can_show_link = contest and (contest.is_over() or contest.is_stage()) or my_stat or stat.get('standings_url')
    has_link_target = stat.get('url') or stat.get('solution') or stat.get('external_solution') or stat.get('standings_url')
    if can_show_link and has_link_target:
        if stat.get('standings_url'):
            link_url = stat['standings_url']
        elif stat.get('url'):
            link_url = stat['url']
        else:
            link_url = reverse('ranking:solution', args=[statistic.pk, key])

        html_parts.append('<a target="_blank" rel="noopener noreferrer"')
        if not (contest and contest.is_stage()) and (stat.get('solution') or stat.get('external_solution')):
            html_parts.append(' class="solution"')
            html_parts.append(' onClick="viewSolution(this, event)"')
            html_parts.append(f' data-url="{html.escape(link_url)}"')
            link_url = reverse('ranking:solution', args=[statistic.pk, key])
        html_parts.append(f' href="{html.escape(link_url)}"')
        html_parts.append('>')

    if stat.get('icon'):
        icon_title = f' title="{html.escape(str(stat["verdict"]))}" data-toggle="tooltip"' if stat.get('verdict') else ''
        html_parts.append(f'<span{icon_title}>{mark_safe(stat["icon"])}</span>')
    elif stat.get('binary') is not None:
        icon_title = f' title="{html.escape(str(stat["verdict"]))}" data-toggle="tooltip"' if stat.get('verdict') else ''
        icon_class = "check" if is_solved(stat) else "times"
        html_parts.append(f'<span{icon_title}><i class="fas fa-{icon_class}"></i></span>')
    elif with_detail and stat.get('subscores'):
        html_parts.append('<span>')
        for i, subscore in enumerate(stat['subscores']):
            if not isinstance(subscore, dict):
                continue
            if i > 0:
                html_parts.append('+')
            subscore_verdict = subscore.get('verdict')
            subscore_title = f' title="{html.escape(str(subscore_verdict))}" data-toggle="tooltip"' if subscore_verdict else ''
            subscore_class = "acc" if subscore.get('result') else "rej"
            html_parts.append(f'<span{subscore_title} class="{subscore_class}">{html.escape(str(subscore.get("status", "")))}</span>')
        html_parts.append('</span>')
    elif normalized_result(stat.get('result')) in {'+', '?'}:
        html_parts.append(f'<span>{html.escape(str(stat["result"]))}</span>')
    elif stat.get('start_time') and (ctx_timezone := context.get('timezone')):
        start_time_dt = timestamp_to_datetime(stat['start_time'])
        title_attr = ''
        if ctx_timezone and start_time_dt and (ctx_timeformat := context.get('timeformat')):
            title_attr = f' title="{html.escape(format_time(timezone(start_time_dt, ctx_timezone), ctx_timeformat))}" data-placement="top" data-toggle="tooltip"'
        countdown_val = countdown(start_time_dt) if start_time_dt else ''
        html_parts.append(f'<span{title_attr} class="small countdown" data-timestamp="{stat["start_time"]}">{countdown_val}</span>')
    elif display_val := (stat.get('result_name') if with_result_name and stat.get('result_name') else scoreformat(stat['result'])):
        result_class = f' class="{stat["result_name_class"]}"' if with_result_name and stat.get('result_name_class') else ''
        result_title = f' title="{html.escape(str(stat["verdict"]))}" data-toggle="tooltip"' if stat.get('verdict') and 'time' in stat else ''
        html_parts.append(f'<span{result_class}{result_title}>{display_val}</span>')

    if with_detail and stat.get('result_rank'):
        html_parts.append(f'<span class="text-muted small text-weight-normal"> ({html.escape(str(stat["result_rank"]))})</span>')

    if can_show_link and has_link_target:
        html_parts.append('</a>')

    if has_alternative_result:
        html_parts.append('</span></a>')

    if stat.get('is_virtual'):
        html_parts.append(f'<span class="is-virtual">{icon_to("is_virtual")}</span>')

    html_parts.append('</div>')

    if (extra_score_val := as_number(stat['extra_score'], force=True)) is not None:
        extra_info_title = ''
        if stat.get('extra_info'):
                extra_info_html = "".join(f"{html.escape(str(info))}<br/>" for info in stat['extra_info'])
                extra_info_title = f' data-toggle="tooltip" data-placement="top" data-html="true" title="{extra_info_html}"'
        prefix = "+" if extra_score_val > 0 else ""
        html_parts.append(f'<div class="inline"{extra_info_title}>{prefix}{scoreformat(extra_score_val)}</div>')

    if with_detail:
        if stat.get('penalty_score') is not None:
            html_parts.append(f'<div class="inline">({html.escape(str(stat["penalty_score"]))})</div>')
        elif stat.get('attempts') is not None:
            html_parts.append(f'<div class="inline">({html.escape(str(stat["attempts"]))})</div>')

    if with_admin_url and perms and perms['ranking']['change_statistics'] and statistic:
        admin_change_url = reverse('admin:ranking_statistics_change', args=[statistic.pk])
        html_parts.append(f'<a href="{admin_change_url}" class="database-link invisible" target="_blank" rel="noopener"><i class="fas fa-database"></i></a>')

    html_parts.append('</div>')

    if with_detail or ('result' not in stat and 'extra_score' not in stat):
        html_parts.append(standings_statistic_problem_detail(context, small=True, stat=stat))

    languages = get_list(request.GET, 'languages')
    if stat.get('language') and languages:
        lang_class = "text-muted" if languages and stat['language'] not in languages and 'any' not in languages else ""
        html_parts.append(f'<small class="{lang_class}"><div class="language">{html.escape(str(stat["language"]))}</div></small>')

    verdicts = get_list(request.GET, 'verdicts')
    if stat.get('verdict') and verdicts:
        verdict_class = "text-muted" if verdicts and stat['verdict'] not in verdicts and 'any' not in verdicts else ""
        html_parts.append(f'<small class="{verdict_class}"><div class="verdict">{html.escape(str(stat["verdict"]))}</div></small>')

    if request.GET.get('ips') and fields_to_select.get('ips'):
        html_parts.append(submission_info_field(stat, 'ip'))

    return mark_safe(" ".join(html_parts))


@register.simple_tag(takes_context=True)
def standings_statistic_problems(context):
    problems = context['problems']
    addition = context['addition']
    addition_problems = addition.get('problems', {})
    tag = context['tag']

    html_parts = []
    for problem in problems:
        key = get_problem_short(problem)
        stat = addition_problems.get(key)
        context['problem'] = problem
        context['key'] = key
        context['stat'] = stat
        attributes = standings_statistic_problem_attributes(context)
        content = standings_statistic_problem(context)
        html_parts.append(f'<{tag} {attributes}>{content}</{tag}>')
        del context['problem']
        del context['key']
        del context['stat']

    return mark_safe("\n".join(html_parts))


@register.filter
def resource_account_types(resource):
    ret = ['user']
    if resource is None or resource.n_university_accounts:
        ret.append('university')
    if resource is None or resource.n_team_accounts:
        ret.append('team')
    return ret
