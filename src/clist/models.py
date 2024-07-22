import calendar
import itertools
import logging
import math
import os
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

import numpy as np
import requests
from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Case, F, Max, Q, When
from django.db.models.expressions import Exists, OuterRef
from django.db.models.functions import Cast, Ln
from django.urls import reverse
from django.utils.timezone import now as timezone_now
from django_ltree.fields import PathField
from PIL import Image, UnidentifiedImageError

from clist.templatetags.extras import get_item, get_problem_key, slug
from logify.models import EventLog, EventStatus
from pyclist.indexes import GistIndexTrgrmOps
from pyclist.models import BaseManager, BaseModel
from utils.colors import color_to_rgb, darken_hls, hls_to_rgb, lighten_hls, rgb_to_color, rgb_to_hls
from utils.timetools import Epoch, parse_duration, timed_cache


class PriorityResourceManager(BaseManager):
    def get_queryset(self):
        ret = super().get_queryset()
        ret = ret.annotate(rval=Cast(Cast('has_rating_history', models.IntegerField()), models.FloatField()))
        ret = ret.annotate(pval=Cast(Cast('has_problem_rating', models.IntegerField()), models.FloatField()))
        priority = Ln(F('n_contests') + 1) + Ln(F('n_accounts') + 1) + 4 * (F('rval') + F('pval'))
        ret = ret.annotate(priority=priority)
        ret = ret.order_by('-priority')
        return ret


class AvailableForUpdateResourceManager(BaseManager):
    def get_queryset(self):
        ret = super().get_queryset()
        with_updating = (Q(has_rating_history=True) | Q(has_country_rating=True) | Q(has_problem_rating=True)
                         | Q(has_accounts_infos_update=True))
        ongoing_contests = Contest.ongoing_objects.filter(resource_id=OuterRef('pk'))
        ret = ret.annotate(has_ongoing_contests=Exists(ongoing_contests))
        ret = ret.filter(~with_updating | Q(has_ongoing_contests=False))

        parse_statistic_in_progress = EventLog.objects.filter(
            name='parse_statistic',
            status=EventStatus.IN_PROGRESS,
            contest__resource_id=OuterRef('pk'),
        )
        ret = ret.annotate(parse_statistic_in_progress=Exists(parse_statistic_in_progress))
        ret = ret.filter(parse_statistic_in_progress=False)

        return ret


class Resource(BaseModel):
    host = models.CharField(max_length=255, unique=True)
    short_host = models.CharField(max_length=20, unique=True, null=True, blank=True)
    enable = models.BooleanField()
    url = models.CharField(max_length=255)
    regexp = models.CharField(max_length=1024, null=True, blank=True)
    path = models.CharField(max_length=255, null=True, blank=True)
    parse_url = models.CharField(max_length=255, null=True, blank=True)
    timezone = models.CharField(max_length=30, null=True, blank=True)
    auto_remove_started = models.BooleanField(default=False, null=False, blank=False)
    color = models.CharField(max_length=20, null=True, blank=True)
    profile_url = models.CharField(max_length=255, null=True, blank=True, default=None)
    avatar_url = models.CharField(max_length=255, null=True, blank=True, default=None)
    problem_url = models.CharField(max_length=255, null=True, blank=True, default=None)
    uid = models.CharField(max_length=100, null=True, blank=True)
    info = models.JSONField(default=dict, blank=True)
    ratings = models.JSONField(default=list, blank=True)
    has_rating_history = models.BooleanField(default=False)
    has_country_rating = models.BooleanField(default=False)
    rating_prediction = models.JSONField(default=None, null=True, blank=True)
    rating_update_time = models.DateTimeField(null=True, blank=True)
    rank_update_time = models.DateTimeField(null=True, blank=True)
    country_rank_update_time = models.DateTimeField(null=True, blank=True)
    contest_update_time = models.DateTimeField(null=True, blank=True)
    has_problem_rating = models.BooleanField(default=False)
    has_problem_update = models.BooleanField(default=False)
    has_multi_account = models.BooleanField(default=False)
    has_accounts_infos_update = models.BooleanField(default=False)
    n_accounts_to_update = models.IntegerField(default=None, null=True, blank=True)
    n_accounts = models.IntegerField(default=0)
    n_contests = models.IntegerField(default=0)
    n_rating_accounts = models.IntegerField(default=None, null=True, blank=True)
    icon = models.CharField(max_length=255, null=True, blank=True)
    accounts_fields = models.JSONField(default=dict, blank=True)
    avg_rating = models.FloatField(default=None, null=True, blank=True)
    has_upsolving = models.BooleanField(default=False)
    has_account_verification = models.BooleanField(default=False)
    has_standings_renamed_account = models.BooleanField(default=False)
    problems_fields = models.JSONField(default=dict, blank=True)
    statistics_fields = models.JSONField(default=dict, blank=True)
    skip_for_contests_chart = models.BooleanField(default=False)

    RATING_FIELDS = ('old_rating', 'new_rating', 'rating', 'rating_perf', 'performance', 'raw_rating',
                     'OldRating', 'Rating', 'NewRating', 'Performance',
                     'predicted_old_rating', 'predicted_new_rating', 'predicted_rating_perf', 'predicted_raw_rating',
                     'rating_prediction_old_rating', 'rating_prediction_new_rating', 'rating_prediction_rating_perf',
                     'rating_prediction_raw_rating')

    event_logs = GenericRelation('logify.EventLog', related_query_name='resource')

    objects = BaseManager()
    priority_objects = PriorityResourceManager()
    available_for_update_objects = AvailableForUpdateResourceManager()

    class Meta:
        indexes = [
            GistIndexTrgrmOps(fields=['host']),
            GistIndexTrgrmOps(fields=['short_host']),
        ]

        permissions = (
            ('update_statistics', 'Can update statistics'),
            ('view_private_fields', 'Can view private fields'),
        )

    def __str__(self):
        return f'{self.host} Resource#{self.id}'

    def href(self, host=None):
        return '{uri.scheme}://{host}/'.format(uri=urlparse(self.url), host=host or self.host)

    def get_rating_color(self, value, ignore_old=False):
        if self.ratings and (value or isinstance(value, (int, float))):
            if isinstance(value, (list, tuple)):
                for v in value:
                    ret = self.get_rating_color(v)
                    if ret[0]:
                        return ret
            elif isinstance(value, dict):
                fields = self.info.get('ratings', {}).get('chartjs', {}).get('coloring_field')
                fields = [fields] if fields else self.RATING_FIELDS
                for field in fields:
                    if ignore_old and field.lower().startswith('old'):
                        continue
                    if field in value:
                        ret = self.get_rating_color(value.get(field))
                        if ret[0]:
                            return ret
                    if 'rating_change' in value and 'new_rating' in value and field.lower().startswith('old'):
                        ret = self.get_rating_color(value.get('new_rating') - value.get('rating_change'))
                        if ret[0]:
                            return ret
            else:
                if isinstance(value, str):
                    value = int(value)
                for rating in self.ratings:
                    if rating['low'] <= value < rating['high'] + rating.get('sign', 1):
                        return rating, value
        return None, None

    def save(self, *args, **kwargs):
        if self.color is None:
            values = []
            for r in Resource.objects.filter(color__isnull=False):
                h, *_ = rgb_to_hls(*color_to_rgb(r.color))
                values.append(h)
            values.sort()

            if values:
                prv = values[-1] - 1
            opt = 0, 0
            for val in values:
                delta, middle, prv = val - prv, (val + prv) * .5, val
                opt = max(opt, (delta, middle))
            self.color = rgb_to_color(*hls_to_rgb(opt[1] % 1, .6, .5))
            self.update_get_events_colors()

        if self.icon is None:
            self.update_icon()

        super().save(*args, **kwargs)

    def update_get_events_colors(self, force=False, alpha=0.7):
        if self.info.get('get_events', {}).get('colors') and not force:
            return
        hue, lightness, saturation = rgb_to_hls(*color_to_rgb(self.color))
        colors = {
            'lighten': rgb_to_color(*hls_to_rgb(*lighten_hls(hue, lightness, saturation, alpha))),
            'darken': rgb_to_color(*hls_to_rgb(*darken_hls(hue, lightness, saturation, alpha))),
        }
        self.info.setdefault('get_events', {})['colors'] = colors

    def update_icon_sizes(self):
        filepath = os.path.join(settings.STATIC_ROOT, self.icon)
        for size in settings.RESOURCES_ICONS_SIZES:
            out_filepath = os.path.join(settings.MEDIA_ROOT, settings.MEDIA_SIZES_PATHDIR, f'{size}x{size}', self.icon)
            os.makedirs(os.path.dirname(out_filepath), exist_ok=True)
            image = Image.open(filepath)
            resized = image.resize((size, size))
            resized.save(out_filepath)

    def change_icon_background_color(self):
        icon_background_color = self.info.get('icon_background_color')
        if not icon_background_color:
            return
        filepath = os.path.join(settings.STATIC_ROOT, self.icon)
        try:
            img = Image.open(filepath).convert('RGBA')
        except UnidentifiedImageError:
            return
        img = np.array(img)
        if img.shape[2] != 4:
            return
        alpha = img[..., 3:] / 255
        bg_color = color_to_rgb(icon_background_color, normalization=255)
        img = (1 - alpha) * bg_color + alpha * img[..., :3]
        img = Image.fromarray(np.round(img).astype(np.uint8))
        img.save(filepath)

    def update_icon(self):

        urls = []
        for parse_url in (self.url, self.href()):
            try:
                response = requests.get(parse_url, timeout=7)
            except Exception as e:
                logging.error(str(e))
                continue

            matches = re.findall(
                r'<link[^>]*rel="([^"]*\bicon\b[^"]*)"[^>]*href="([^"]*)"[^>]*>',
                response.content.decode('utf8', errors='ignore'),
                re.IGNORECASE,
            )

            for rel, match in matches:
                if '-icon' in rel:
                    continue
                match = re.sub(r'\?.*$', '', match)
                sizes = list(map(int, re.findall('[0-9]+', match)))
                size = sizes[-1] if sizes else 0
                *_, ext = os.path.splitext(match)
                if not match.startswith('/') and not match.startswith('http'):
                    match = '/' + match
                urls.append((size, urljoin(response.url, match), (ext or '.png')))
            if urls:
                break
        urls.sort(reverse=True)
        urls.append((None, f'https://www.google.com/s2/favicons?domain={self.host}', '.ico'))

        for _, url, ext in urls:
            response = requests.get(url)
            if response.status_code == 200:
                filename = re.sub('[./]', '_', self.host) + ext
                relpath = os.path.join(settings.RESOURCES_ICONS_PATHDIR, filename)
                filepath = os.path.join(settings.STATIC_ROOT, relpath)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)

                with open(filepath, 'wb') as fo:
                    fo.write(response.content)

                try:
                    img = Image.open(filepath).convert('RGBA')
                except UnidentifiedImageError:
                    continue
                img.save(filepath)

                filepath = os.path.join(settings.REPO_STATIC_ROOT, relpath)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                img.save(filepath)

                self.icon = relpath
                self.save()
                break
        else:
            return

        if self.icon:
            self.change_icon_background_color()
            self.update_icon_sizes()

    @property
    def plugin(self):
        if not hasattr(self, 'plugin_'):
            if not self.module:
                self.plugin_ = None
            else:
                self.plugin_ = __import__(self.module.path.replace('/', '.'), fromlist=['Statistic'])
        return self.plugin_

    def with_single_account(self, account=None):
        return (
            not self.has_multi_account
            or (account is not None and account.rating is not None)
        )

    def with_multi_account(self):
        return self.has_multi_account

    def is_major_kind(self, instance):
        if not instance:
            return True
        if isinstance(instance, str):
            return instance == self.info.get('major_kind')
        if isinstance(instance, Contest):
            return self.is_major_kind(instance.kind)
        if isinstance(instance, Iterable):
            return any(self.is_major_kind(kind) for kind in instance)
        raise ValueError(f'Invalid instance type = {type(instance)}')

    def major_contests(self):
        major_kind = self.info.get('major_kind')
        return self.contest_set.filter(Q(kind=major_kind) | Q(kind__isnull=True) | Q(kind=''))

    def rating_step(self):
        prev = 0
        step = 0
        for rating in self.ratings[:-1]:
            step = math.gcd(step, rating['next'] - prev)
            prev = rating['next']
        return step

    def account_verification_fields(self):
        verification_fields = self.accounts_fields.get('verification_fields', [])
        ret = [field for field, values in self.accounts_fields.get('types', {}).items() if 'str' in values]
        if verification_fields:
            ret = [field for field in ret if field in verification_fields]
        return ret

    @classmethod
    def get_object(cls, value):
        condition = Q(pk=value) if value.isdigit() else Q(host__contains=value)
        return Resource.objects.get(condition)


class BaseContestManager(BaseManager):
    pass


class VisibleContestManager(BaseContestManager):
    def get_queryset(self):
        return super().get_queryset().filter(invisible=0).filter(stage__isnull=True)


class SignificantContestManager(VisibleContestManager):
    def get_queryset(self):
        return super().get_queryset().filter(related__isnull=True)


class OngoingContestManager(SignificantContestManager):
    def get_queryset(self):
        ret = super().get_queryset()
        ret = Contest.objects.annotate(
            duration_time=Epoch(F('end_time') - F('start_time'))
        ).filter(
            resource__module__isnull=False,
            duration_time__lt=Epoch('resource__module__long_contest_idle'),
            start_time__lt=timezone_now() + timedelta(hours=1),
            end_time__gt=timezone_now() - timedelta(hours=1),
        )
        return ret


class Contest(BaseModel):
    STANDINGS_KINDS = {
        'icpc': 'ICPC',
        'scoring': 'SCORING',
        'cf': 'CF',
    }

    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    kind = models.CharField(max_length=30, blank=True, null=True, db_index=True)
    title = models.CharField(max_length=2048)
    slug = models.CharField(max_length=2048, null=True, blank=True, db_index=True)
    title_path = PathField(null=True, blank=True, db_index=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    duration_in_secs = models.IntegerField(null=False, blank=True)
    url = models.CharField(max_length=255)
    key = models.CharField(max_length=255)
    host = models.CharField(max_length=255)
    uid = models.CharField(max_length=100, null=True, blank=True)
    edit = models.CharField(max_length=100, null=True, blank=True)
    invisible = models.BooleanField(default=False, db_index=True)
    standings_url = models.CharField(max_length=2048, null=True, blank=True)
    trial_standings_url = models.CharField(max_length=2048, null=True, blank=True)
    standings_kind = models.CharField(max_length=10, blank=True, null=True, db_index=True,
                                      choices=STANDINGS_KINDS.items())
    registration_url = models.CharField(max_length=2048, null=True, blank=True)
    calculate_time = models.BooleanField(default=False)
    info = models.JSONField(default=dict, blank=True)
    writers = models.ManyToManyField('ranking.Account', blank=True, related_name='writer_set')
    n_statistics = models.IntegerField(null=True, blank=True, db_index=True)
    n_problems = models.IntegerField(null=True, blank=True, db_index=True)
    parsed_time = models.DateTimeField(null=True, blank=True)
    has_hidden_results = models.BooleanField(null=True, blank=True)
    related = models.ForeignKey('Contest', null=True, blank=True, on_delete=models.SET_NULL, related_name='related_set')
    merging_contests = models.ManyToManyField('Contest', blank=True, related_name='merged_set')
    is_rated = models.BooleanField(null=True, blank=True, default=None, db_index=True)
    with_medals = models.BooleanField(null=True, blank=True, default=None, db_index=True)
    with_advance = models.BooleanField(null=True, blank=True, default=None, db_index=True)
    series = models.ForeignKey('ContestSeries', null=True, blank=True, default=None, on_delete=models.SET_NULL)
    allow_updating_statistics_for_participants = models.BooleanField(null=True, blank=True, default=None, db_index=True)
    set_matched_coders_to_members = models.BooleanField(null=True, blank=True, default=None)

    notification_timing = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    statistic_timing = models.DateTimeField(default=None, null=True, blank=True)
    rating_prediction_timing = models.DateTimeField(default=None, null=True, blank=True)
    wait_for_successful_update_timing = models.DateTimeField(default=None, null=True, blank=True)
    statistics_update_required = models.BooleanField(default=False)

    rating_prediction_fields = models.JSONField(default=dict, blank=True, null=True)
    has_fixed_rating_prediction_field = models.BooleanField(default=False, null=True, blank=True)
    rating_prediction_hash = models.CharField(max_length=64, default=None, null=True, blank=True)

    problem_rating_hash = models.CharField(max_length=64, default=None, null=True, blank=True)
    problem_rating_update_required = models.BooleanField(default=False)

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True, db_index=True)
    was_auto_added = models.BooleanField(default=False)
    auto_updated = models.DateTimeField(auto_now_add=True)

    event_logs = GenericRelation('logify.EventLog', related_query_name='contest')
    virtual_starts = GenericRelation('ranking.VirtualStart', related_query_name='contest')

    has_submissions = models.BooleanField(default=None, null=True, blank=True, db_index=True)
    has_submissions_tests = models.BooleanField(default=None, null=True, blank=True, db_index=True)

    is_promoted = models.BooleanField(default=None, null=True, blank=True, db_index=True)

    objects = BaseContestManager()
    visible = VisibleContestManager()
    significant = SignificantContestManager()
    ongoing_objects = OngoingContestManager()

    class Meta:
        unique_together = ('resource', 'key', )

        indexes = [
            models.Index(fields=['invisible']),
            models.Index(fields=['start_time']),
            models.Index(fields=['end_time']),
            models.Index(fields=['updated']),
            models.Index(fields=['n_statistics', 'updated']),
            models.Index(fields=['n_statistics', 'end_time']),
            models.Index(fields=['resource', 'end_time', 'id']),
            models.Index(fields=['resource', '-end_time', '-id']),
            models.Index(fields=['end_time', 'id']),
            models.Index(fields=['-end_time', '-id']),
            models.Index(fields=['resource', 'start_time', 'id']),
            models.Index(fields=['resource', 'notification_timing', 'start_time', 'end_time']),
            models.Index(fields=['resource', 'statistic_timing', 'start_time', 'end_time']),
            models.Index(fields=['resource', '-n_statistics']),
            models.Index(fields=['resource', '-n_problems']),
            models.Index(fields=['title']),
            GistIndexTrgrmOps(fields=['title']),
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prev_is_rated = self.is_rated

    def save(self, *args, **kwargs):
        if self.duration_in_secs is None:
            self.duration_in_secs = (self.end_time - self.start_time).total_seconds()
        self.slug = slug(self.title)
        self.title_path = self.slug.replace('-', '.')

        fields = self.info.get('fields', [])

        if self.is_rated is None:
            is_rated = self.related_id is None and (
                'new_rating' in fields or
                'rating_change' in fields or
                '_rating_data' in fields
            )
            if is_rated:
                self.is_rated = True
        if not self.is_rated and self.prev_is_rated:
            stats = self.statistics_set
            stats = stats.filter(new_global_rating__isnull=False)
            stats.update(new_global_rating=None, global_rating_change=None)

        if self.is_over():
            self.with_medals = bool(get_item(self.info, 'standings.medals')) or 'medal' in fields
            self.with_advance = 'advanced' in fields or '_advance' in fields

        if not self.kind:
            if hasattr(self, 'stage'):
                self.kind = 'stage'
            elif self.invisible:
                self.kind = 'hidden'

        last_index = None
        min_index = None
        wrong_rating_order = False
        rating_order_fields = ('old_rating', 'rating_change', 'new_rating')
        for field in rating_order_fields:
            if field in fields:
                index = fields.index(field)
                if min_index is None or min_index > index:
                    min_index = index
                if last_index is not None and last_index > index:
                    wrong_rating_order = True
                last_index = index
        if wrong_rating_order:
            for field in rating_order_fields[::-1]:
                if field in fields:
                    fields.remove(field)
                    fields.insert(min_index, field)
            self.info['fields'] = fields

        hidden_fields = self.info.get('hidden_fields', [])
        if 'old_rating' in fields and 'old_rating' not in hidden_fields:
            hidden_fields.append('old_rating')
        if 'rating_change' in fields and 'rating_change' not in hidden_fields and 'new_rating' in fields:
            hidden_fields.append('rating_change')
        self.info['hidden_fields'] = hidden_fields

        return super().save(*args, **kwargs)

    def is_over(self):
        return self.end_time <= timezone_now()

    def is_running(self):
        return not self.is_over() and self.start_time <= timezone_now()

    def is_coming(self):
        return timezone_now() < self.start_time

    @property
    def next_time(self):
        return self.next_time_to(None)

    def next_time_to(self, now):
        if self.is_over():
            return 0
        delta = self.next_time_datetime() - (now or timezone_now())
        seconds = delta.total_seconds()
        return int(round(seconds))

    def next_time_datetime(self):
        return self.end_time if self.is_running() else self.start_time

    def __str__(self):
        return f'{self.title} Contest#{self.id}'

    @property
    def duration(self):
        return timedelta(seconds=self.duration_in_secs)

    @property
    def full_duration(self):
        return self.end_time - self.start_time

    @property
    def hr_duration(self):
        duration = self.duration
        if duration > timedelta(days=999):
            return "%d years" % (duration.days // 364)
        elif duration > timedelta(days=3):
            return "%d days" % duration.days
        else:
            total = duration.total_seconds()
            return "%02d:%02d" % ((total + 1e-9) // 3600, (total + 1e-9) % 3600 // 60)

    @classmethod
    def month_regex(cls):
        if not hasattr(cls, '_month_regex'):
            months = itertools.chain(calendar.month_name, calendar.month_abbr)
            regex = '|'.join([f'[{m[0]}{m[0].lower()}]{m[1:]}' for m in months if m])
            cls._month_regex = rf'\b(?:{regex})\b'
        return cls._month_regex

    @staticmethod
    def title_neighbors_(title, deep, viewed):
        viewed.add(title)
        if deep == 0:
            return

        for match in re.finditer(rf'([0-9]+|[A-Z]\b|{Contest.month_regex()})', title):
            for delta in (-1, 1):
                base_title = title
                value = match.group(0)
                values = []
                if value.isdigit():
                    value = str(int(value) + delta)
                elif len(value) == 1:
                    value = chr(ord(value) + delta)
                else:
                    mformat = '%b' if len(value) == 3 else '%B'
                    index = datetime.strptime(value.title(), mformat).month
                    mformats = ['%b', '%B'] if index == 5 else [mformat]
                    if not (1 <= index + delta <= 12):
                        ym = re.search(r'\b[0-9]{4}\b', base_title)
                        if ym:
                            year = str(int(ym.group()) + delta)
                            base_title = base_title[:ym.start()] + year + base_title[ym.end():]
                    index = (index - 1 + delta) % 12 + 1
                    for mformat in mformats:
                        values.append(datetime.strptime(str(index), '%m').strftime(mformat))
                values = values or [value]
                for value in values:
                    new_title = base_title[:match.start()] + value + base_title[match.end():]
                    if new_title in viewed:
                        continue
                    Contest.title_neighbors_(new_title, deep=deep - 1, viewed=viewed)

    def neighbors(self):
        viewed = set()
        Contest.title_neighbors_(self.title, deep=1, viewed=viewed)

        qs = None

        def add(q):
            nonlocal qs
            if qs is None:
                qs = q
            else:
                qs = qs | q

        viewed.discard(self.title)
        if viewed:
            cond = Q()
            for title in viewed:
                cond |= Q(title=title)
            add(Contest.objects.filter(cond))

        resource_contests = Contest.objects.filter(resource=self.resource_id)

        for query, order in (
            (Q(end_time__lt=self.end_time), '-end_time'),
            (Q(end_time__gt=self.end_time), 'start_time'),
        ):
            q = resource_contests.filter(query).order_by(order)
            add(q[:1])

            if self.title_path is not None:
                q = resource_contests.filter(query)
                q = q.extra(select={'lcp': f'''nlevel(lca(title_path, '{self.title_path}'))'''})
                q = q.order_by('-lcp', order)
                add(q[:1])

        if qs is not None:
            qs = qs.order_by('end_time', 'id')
        else:
            qs = []
        return qs

    def get_timeline_info(self):
        ret = self.resource.info.get('standings', {}).get('timeline', {})
        ret.update(self.info.get('standings', {}).get('timeline', {}))
        return ret

    @property
    def actual_url(self):
        if self.n_statistics or self.info.get('problems'):
            return settings.HTTPS_HOST_URL_ + reverse('ranking:standings', args=(slug(self.title), self.pk))
        if self.registration_url and self.is_coming():
            return self.registration_url
        if self.url and self.is_coming():
            return self.url
        if self.standings_url and not self.is_coming():
            return self.standings_url
        return self.url

    def is_major_kind(self):
        return self.resource.is_major_kind(self.kind)

    @property
    def standings_start_time(self):
        start_time = self.info.get('custom_start_time')
        if start_time:
            return datetime.fromtimestamp(start_time, tz=timezone.utc)
        return self.start_time

    @property
    def time_percentage(self):
        if self.is_coming():
            return 0
        if self.is_over() or not self.duration_in_secs or not self.parsed_time:
            return 1
        ret = (self.parsed_time - self.standings_start_time).total_seconds() / self.duration_in_secs
        return max(min(ret, 1), 0)

    @property
    def standings_per_page(self):
        per_page = self.info.get('standings', {}).get('per_page', 50)
        if per_page is None:
            per_page = 100500
        elif self.n_statistics and self.n_statistics <= 500:
            per_page = self.n_statistics
        return per_page

    @property
    def problems_list(self):
        problems = self.info.get('problems')
        if not problems:
            return
        if isinstance(problems, dict):
            division_problems = list(problems.get('division', {}).values())
            problems = []
            for a in division_problems:
                problems.extend(a)
        if isinstance(problems, list):
            seen = set()
            name_grouping = False
            for problem in problems:
                name_grouping = name_grouping or 'subname' in problem or 'full_score' in problem
                ok = True
                for field, value in (
                    ('key', get_problem_key(problem)),
                    ('group', problem.get('group')),
                    ('name', problem.get('name') if name_grouping else None),
                ):
                    if not value:
                        continue
                    if (field, value) in seen:
                        ok = False
                    else:
                        seen.add((field, value))
                if ok:
                    yield problem
        else:
            raise ValueError(f'Unknown problems types = {type(problems)}')

    @property
    def full_score(self):
        if 'full_score' in self.info:
            return self.info['full_score']
        full_score = 0
        for problem in self.problems_list:
            full_score += problem.get('full_score', 1)
        return full_score

    @property
    def division_problems(self):
        problems = self.info.get('problems')
        if not problems:
            return []
        if isinstance(problems, dict) and 'division' in problems:
            return problems['division'].items()
        return [(None, problems)]

    def set_series(self, series_name):
        if series_name is None:
            series = None
        else:
            series_slug = slug(series_name)
            series = ContestSeries.objects.filter(Q(name=series_name) | Q(slug=series_slug)).first()
            if series is None:
                series_alias_filter = Q(aliases__contains=series_name) | Q(aliases__contains=series_slug)
                series = ContestSeries.objects.filter(series_alias_filter).first()
            if series is None:
                series = ContestSeries.objects.create(name=series_name, short=series_name)
        self.series = series
        self.save(update_fields=['series'])

    @property
    def is_rating_prediction_timespan(self):
        timespan = self.resource.rating_prediction.get('timespan')
        return not timespan or timezone_now() < self.end_time + parse_duration(timespan)

    @property
    def has_rating_prediction(self):
        return self.has_fixed_rating_prediction_field and self.is_rating_prediction_timespan

    @property
    def channel_update_statistics_group_name(self):
        return f'{self.channel_group_name}__update_statistics'

    def require_statistics_update(self):
        if not self.statistics_update_required:
            self.statistics_update_required = True
            self.save(update_fields=['statistics_update_required'])

    def require_problem_rating_update(self):
        if not self.problem_rating_update_required:
            self.problem_rating_update_required = True
            self.save(update_fields=['problem_rating_update_required'])

    def statistics_update_done(self):
        if self.statistics_update_required:
            self.statistics_update_required = False
            self.save(update_fields=['statistics_update_required'])

    def problem_rating_update_done(self):
        if self.problem_rating_update_required:
            self.problem_rating_update_required = False
            self.save(update_fields=['problem_rating_update_required'])


class ContestSeries(BaseModel):
    name = models.TextField(unique=True, db_index=True, null=False)
    short = models.TextField(unique=True, db_index=True, null=False)
    slug = models.TextField(unique=True, db_index=True, null=False, blank=True)
    aliases = models.JSONField(default=list, blank=True)

    def save(self, *args, **kwargs):
        self.slug = slug(self.short)
        if self.slug not in self.aliases:
            self.aliases.append(self.slug)
        return super().save(*args, **kwargs)

    @property
    def text(self):
        return self.name if self.name.startswith(self.short) else f'{self.short} ({self.name})'

    def __str__(self):
        return f'{self.name} Series#{self.id}'

    class Meta:
        verbose_name_plural = 'Contest series'


class VisibleProblemManager(BaseContestManager):
    def get_queryset(self):
        return super().get_queryset().filter(visible=True)


class Problem(BaseModel):
    contest = models.ForeignKey(Contest, null=True, blank=True, on_delete=models.CASCADE,
                                related_name='individual_problem_set')
    contests = models.ManyToManyField(Contest, blank=True, related_name='problem_set')
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    time = models.DateTimeField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    index = models.SmallIntegerField(null=True)
    key = models.TextField()
    name = models.TextField()
    slug = models.TextField(default=None, null=True, blank=True)
    short = models.TextField(default=None, null=True, blank=True)
    url = models.TextField(default=None, null=True, blank=True)
    archive_url = models.TextField(default=None, null=True, blank=True)
    divisions = ArrayField(models.TextField(), default=None, null=True, blank=True)
    n_attempts = models.IntegerField(default=None, null=True, blank=True)
    n_accepted = models.IntegerField(default=None, null=True, blank=True)
    n_partial = models.IntegerField(default=None, null=True, blank=True)
    n_hidden = models.IntegerField(default=None, null=True, blank=True)
    n_total = models.IntegerField(default=None, null=True, blank=True)
    visible = models.BooleanField(default=True, null=False)
    rating = models.IntegerField(default=None, null=True, blank=True, db_index=True)
    skip_rating = models.BooleanField(default=None, null=True, blank=True)
    info = models.JSONField(default=dict, blank=True)

    activities = GenericRelation('favorites.Activity', related_query_name='problem')
    notes = GenericRelation('notes.Note', related_query_name='problem')

    objects = BaseManager()
    visible_objects = VisibleProblemManager()

    def __str__(self):
        return f'{self.name} Problem#{self.id}'

    class Meta:
        unique_together = ('contest', 'key')

        indexes = [
            models.Index(fields=['resource_id', 'url', '-time', 'contest_id', 'index']),
            models.Index(fields=['-time', 'contest_id', 'index']),
            models.Index(fields=['resource_id', 'rating']),
            models.Index(fields=['resource_id', 'key']),
            GistIndexTrgrmOps(fields=['name']),
        ]

    def save(self, *args, **kwargs):
        self.visible = self.visible and (bool(self.url) or self.key != self.name)
        super().save(*args, **kwargs)

    @property
    def code(self):
        return self.key

    @property
    def actual_url(self):
        return self.archive_url or self.url

    @staticmethod
    def is_special_info_field(field):
        if not field:
            return False
        if field[0] == '_' or field[-1] == '_' or '___' in field:
            return True
        if field in {'first_ac'}:
            return True

    def rating_is_coming(self):
        return self.end_time <= timezone_now() <= self.end_time + self.resource.module.max_delay_after_end

    def rating_status(self):
        now = timezone_now()
        if now < self.end_time:
            return "waiting for end of contest"
        if self.n_hidden:
            return "waiting unfreeze"
        if self.end_time + self.resource.module.max_delay_after_end < now:
            return "expired"
        return "in progress"

    def has_rating(self):
        return (
            self.n_total
            and not self.skip_rating
            and self.resource.has_problem_rating
            and self.resource.is_major_kind(self.contests.all())
        )

    @staticmethod
    @timed_cache('15m')
    def cached_get(contest, short) -> Optional['Problem']:
        try:
            return Problem.objects.get(Q(short=short) & (Q(contest=contest) | Q(contests=contest)))
        except Problem.DoesNotExist:
            return None


class ProblemTag(BaseModel):
    name = models.TextField(unique=True, db_index=True, null=False)
    problems = models.ManyToManyField(Problem, blank=True, related_name='tags')


class ProblemVerdict(models.TextChoices):
    SOLVED = 'AC'  # accepted
    REJECT = 'WA'  # wrong answer
    HIDDEN = 'HT'  # hidden test
    PARTIAL = 'PS'  # partial solution
    UNKNOWN = '??'  # unknown verdict


class Banner(BaseModel):
    name = models.CharField(max_length=255)
    url = models.URLField()
    end_time = models.DateTimeField()
    template = models.CharField(max_length=255, null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)
    enable = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.name} Banner#{self.id}'

    @property
    def next_time(self):
        now = timezone_now()
        if self.end_time < now:
            return 0
        return int(round((self.end_time - now).total_seconds()))


class PromotionManager(models.Manager):
    def get_queryset(self):
        qs = super().get_queryset().filter(contest__is_promoted=True, enable=True)
        qs = qs.annotate(target_time=Case(
            When(time_attribute='start_time', then=F('contest__start_time')),
            When(time_attribute='end_time', then=F('contest__end_time')),
        ))
        qs = qs.filter(target_time__gt=timezone_now())
        qs = qs.order_by('target_time')
        return qs


class PromotionTimeAttribute(models.TextChoices):
    START_TIME = 'start_time'
    END_TIME = 'end_time'


class Promotion(BaseModel):
    name = models.CharField(max_length=50)
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
    timer_message = models.CharField(max_length=200, null=True, blank=True)
    time_attribute = models.CharField(max_length=50, choices=PromotionTimeAttribute.choices)
    enable = models.BooleanField(default=True, null=True, blank=True)
    background = models.ImageField(upload_to='promotions', null=True, blank=True)

    objects = BaseManager()
    promoting = PromotionManager()

    class Meta:
        unique_together = ('contest', 'time_attribute', )

    def __str__(self):
        return f'{self.name} Promotion#{self.id}'

    def save(self, *args, **kwargs):
        ret = super().save(*args, **kwargs)
        contest = self.contest
        contest.is_promoted = contest.promotion_set.filter(enable=True).exists()
        contest.save(update_fields=['is_promoted'])
        return ret


class PromoLinkManager(BaseManager):

    def get_queryset(self):
        return super().get_queryset().filter(enable=True).order_by('order')


class PromoLink(BaseModel):
    name = models.CharField(max_length=200)
    desc = models.TextField(default=None, null=True, blank=True)
    icon = models.ImageField(upload_to='promolinks', null=True, blank=True)
    url = models.URLField()
    order = models.IntegerField(default=None, blank=True)
    enable = models.BooleanField(default=True)

    objects = BaseManager()
    enabled_objects = PromoLinkManager()

    def save(self, *args, **kwargs):
        if self.order is None:
            max_order = PromoLink.objects.exclude(pk=self.pk).aggregate(Max('order'))['order__max']
            self.order = (max_order or 0) + 1
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} PromoLink#{self.id}'
