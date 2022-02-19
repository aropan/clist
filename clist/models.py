import calendar
import itertools
import logging
import os
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import requests
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django_ltree.fields import PathField
from PIL import Image, UnidentifiedImageError

from clist.templatetags.extras import slug
from pyclist.indexes import GistIndexTrgrmOps
from pyclist.models import BaseManager, BaseModel
from utils.colors import color_to_rgb, darken_hls, hls_to_rgb, lighten_hls, rgb_to_color, rgb_to_hls


class Resource(BaseModel):
    host = models.CharField(max_length=255, unique=True)
    short_host = models.CharField(max_length=20, unique=True, null=True, blank=True)
    enable = models.BooleanField()
    url = models.CharField(max_length=255)
    regexp = models.CharField(max_length=1024, null=True, blank=True)
    path = models.CharField(max_length=255, null=True, blank=True)
    parse_url = models.CharField(max_length=255, null=True, blank=True)
    timezone = models.CharField(max_length=30, null=True, blank=True)
    color = models.CharField(max_length=20, null=True, blank=True)
    profile_url = models.CharField(max_length=255, null=True, blank=True, default=None)
    avatar_url = models.CharField(max_length=255, null=True, blank=True, default=None)
    uid = models.CharField(max_length=100, null=True, blank=True)
    info = models.JSONField(default=dict, blank=True)
    ratings = models.JSONField(default=list, blank=True)
    has_rating_history = models.BooleanField(default=False)
    n_accounts = models.IntegerField(default=0)
    n_contests = models.IntegerField(default=0)
    icon = models.CharField(max_length=255, null=True, blank=True)
    accounts_fields = models.JSONField(default=dict, blank=True)

    RATING_FIELDS = ('old_rating', 'OldRating', 'new_rating', 'NewRating', 'rating', 'Rating')

    objects = BaseManager()

    class Meta:
        indexes = [
            GistIndexTrgrmOps(fields=['host']),
            GistIndexTrgrmOps(fields=['short_host']),
        ]

    def __str__(self):
        return "%s" % (self.host)

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
                    if rating['low'] <= value <= rating['high']:
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
                relpath = os.path.join('img', 'resources', filename)
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

    @property
    def plugin(self):
        if not hasattr(self, 'plugin_'):
            if not self.module:
                self.plugin_ = None
            else:
                self.plugin_ = __import__(self.module.path.replace('/', '.'), fromlist=['Statistic'])
        return self.plugin_

    def with_single_account(self):
        return not self.module or not self.module.multi_account_allowed


class VisibleContestManager(BaseManager):
    def get_queryset(self):
        return super().get_queryset().filter(invisible=0).filter(stage__isnull=True)


class SignificantContestManager(VisibleContestManager):
    def get_queryset(self):
        return super().get_queryset().filter(related__isnull=True)


class Contest(BaseModel):
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
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
    calculate_time = models.BooleanField(default=False)
    info = models.JSONField(default=dict, blank=True)
    writers = models.ManyToManyField('ranking.Account', blank=True, related_name='writer_set')
    n_statistics = models.IntegerField(null=True, blank=True, db_index=True)
    parsed_time = models.DateTimeField(null=True, blank=True)
    has_hidden_results = models.BooleanField(null=True, blank=True)
    related = models.ForeignKey('Contest', null=True, blank=True, on_delete=models.SET_NULL, related_name='related_set')

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True, db_index=True)
    was_auto_added = models.BooleanField(default=False)

    objects = BaseManager()
    visible = VisibleContestManager()
    significant = SignificantContestManager()

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
            models.Index(fields=['resource', 'start_time', 'id']),
            models.Index(fields=['title']),
            GistIndexTrgrmOps(fields=['title']),
        ]

    def save(self, *args, **kwargs):
        if self.duration_in_secs is None:
            self.duration_in_secs = (self.end_time - self.start_time).total_seconds()
        self.slug = slug(self.title)
        self.title_path = self.slug.replace('-', '.')
        return super(Contest, self).save(*args, **kwargs)

    def is_over(self):
        return self.end_time <= timezone.now()

    def is_running(self):
        return not self.is_over() and self.start_time < timezone.now()

    def is_coming(self):
        return timezone.now() < self.start_time

    @property
    def next_time(self):
        return self.next_time_to(None)

    def next_time_to(self, now):
        if self.is_over():
            return 0
        return int(round(
            (
                (
                    self.end_time
                    if self.is_running()
                    else self.start_time
                ) - (now or timezone.now())
            ).total_seconds()
        ))

    def __str__(self):
        return "%s [%d]" % (self.title, self.id)

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
            qs = qs.order_by('end_time')
        else:
            qs = []
        return qs

    def get_timeline_info(self):
        ret = self.resource.info.get('standings', {}).get('timeline', {})
        ret.update(self.info.get('standings', {}).get('timeline', {}))
        return ret

    @property
    def actual_url(self):
        if self.n_statistics:
            return reverse('ranking:standings', args=(slug(self.title), self.pk))
        if self.standings_url:
            return self.standings_url
        return self.url


class Problem(BaseModel):
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    time = models.DateTimeField()
    index = models.SmallIntegerField(null=True)
    key = models.TextField()
    name = models.TextField()
    short = models.TextField(default=None, null=True, blank=True)
    url = models.TextField(default=None, null=True, blank=True)
    divisions = ArrayField(models.TextField(), default=None, null=True, blank=True)
    n_tries = models.IntegerField(default=None, null=True, blank=True)
    n_accepted = models.IntegerField(default=None, null=True, blank=True)
    n_partial = models.IntegerField(default=None, null=True, blank=True)
    n_total = models.IntegerField(default=None, null=True, blank=True)
    visible = models.BooleanField(default=True, null=False)

    def __str__(self):
        return "%s [%d]" % (self.name, self.id)

    class Meta:
        unique_together = ('contest', 'key')

        indexes = [
            models.Index(fields=['resource_id', 'url', '-time', 'contest_id', 'index']),
            models.Index(fields=['-time', 'contest_id', 'index']),
            GistIndexTrgrmOps(fields=['name']),
        ]

    def save(self, *args, **kwargs):
        self.visible = self.visible and (bool(self.url) or self.key != self.name)
        super().save(*args, **kwargs)


class ProblemTag(BaseModel):
    name = models.TextField(unique=True, db_index=True, null=False)
    problems = models.ManyToManyField(Problem, blank=True, related_name='tags')


class TimingContest(BaseModel):
    contest = models.OneToOneField(Contest, related_name='timing', on_delete=models.CASCADE)
    notification = models.DateTimeField(auto_now_add=True, blank=True)
    statistic = models.DateTimeField(default=None, null=True, blank=True)

    def __str__(self):
        return '%s timing, modified = %s' % (str(self.contest), self.modified)


class Banner(BaseModel):
    name = models.CharField(max_length=255)
    url = models.URLField()
    end_time = models.DateTimeField()
    template = models.CharField(max_length=255, null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)
    enable = models.BooleanField(default=True)

    def __str__(self):
        return 'Banner %s' % self.name

    @property
    def next_time(self):
        now = timezone.now()
        if self.end_time < now:
            return 0
        return int(round((self.end_time - now).total_seconds()))
