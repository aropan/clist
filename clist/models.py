import os
import re
import colorsys
import calendar
import itertools
import logging
from urllib.parse import urlparse, urljoin
from datetime import timedelta, datetime

import requests
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.contrib.postgres.fields import JSONField, ArrayField
from django_ltree.fields import PathField
from sql_util.utils import Exists
from PIL import Image


from pyclist.models import BaseModel, BaseManager
from pyclist.indexes import GistIndexTrgrmOps
from clist.templatetags.extras import slug


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
    info = JSONField(default=dict, blank=True)
    ratings = JSONField(default=list, blank=True)
    has_rating_history = models.BooleanField(default=False)
    n_accounts = models.IntegerField(default=0)
    n_contests = models.IntegerField(default=0)
    icon = models.CharField(max_length=255, null=True, blank=True)

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

    def get_rating_color(self, value):
        if self.ratings and (value or isinstance(value, (int, float))):
            if isinstance(value, (list, tuple)):
                for v in value:
                    ret = self.get_rating_color(v)
                    if ret[0]:
                        return ret
            elif isinstance(value, dict):
                for field in self.RATING_FIELDS:
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
                color = [int(r.color[i:i + 2], 16) / 255. for i in range(1, 6, 2)]
                h, _, _ = colorsys.rgb_to_hls(*color)
                values.append(h)
            values.sort()

            if values:
                prv = values[-1] - 1
            opt = 0, 0
            for val in values:
                delta, middle, prv = val - prv, (val + prv) * .5, val
                opt = max(opt, (delta, middle))
            h = opt[1] % 1
            color = colorsys.hls_to_rgb(h, .6, .5)

            self.color = '#' + ''.join(f'{int(c * 255):02x}' for c in color).upper()

        if self.icon is None:
            self.update_icon()

        super().save(*args, **kwargs)

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

                Image.open(filepath).convert('RGBA').save(filepath)

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


class VisibleContestManager(BaseManager):
    def get_queryset(self):
        return super(VisibleContestManager, self).get_queryset().filter(invisible=0).filter(stage__isnull=True)


class Contest(models.Model):
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
    invisible = models.BooleanField(default=False)
    standings_url = models.CharField(max_length=2048, null=True, blank=True)
    calculate_time = models.BooleanField(default=False)
    info = JSONField(default=dict, blank=True)
    writers = models.ManyToManyField('ranking.Account', blank=True, related_name='writer_set')
    n_statistics = models.IntegerField(null=True, blank=True, db_index=True)

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True, db_index=True)
    was_auto_added = models.BooleanField(default=False)

    objects = BaseManager()
    visible = VisibleContestManager()

    class Meta:
        unique_together = ('resource', 'key', )

        indexes = [
            models.Index(fields=['start_time']),
            models.Index(fields=['end_time']),
            models.Index(fields=['updated']),
            models.Index(fields=['n_statistics', 'updated']),
            GistIndexTrgrmOps(fields=['title']),
        ]

    def save(self, *args, **kwargs):
        if self.duration_in_secs is None:
            self.duration_in_secs = (self.end_time - self.start_time).total_seconds()
        self.slug = slug(self.title).strip('-')
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
        # Fix for virtual contest
        # return self.end_time - self.start_time

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

        cond = Q()
        for title in viewed:
            cond |= Q(title=title)

        resource_contests = Contest.objects.filter(resource=self.resource_id)
        resource_contests = resource_contests.annotate(has_statistics=Exists('statistics')).filter(has_statistics=True)

        for query, order in (
            (Q(end_time__lt=self.start_time), '-end_time'),
            (Q(start_time__gt=self.end_time), 'start_time'),
        ):
            c = resource_contests.filter(query).order_by(order).first()
            if c:
                cond |= Q(pk=c.pk)

            if self.title_path is not None:
                qs = resource_contests.filter(query).exclude(title=self.title)
                qs = qs.extra(select={'lcp': f'''nlevel(lca(title_path, '{self.title_path}'))'''})
                qs = qs.order_by('-lcp', order)
                c = qs.first()
                if c and c.lcp:
                    cond |= Q(pk=c.pk)

        qs = resource_contests.filter(cond).exclude(pk=self.pk).order_by('end_time')

        return qs


class Problem(BaseModel):
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
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
            GistIndexTrgrmOps(fields=['name']),
        ]

    def save(self, *args, **kwargs):
        self.visible = bool(self.url) or self.key != self.name
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
    data = JSONField(default=dict, blank=True)
    enable = models.BooleanField(default=True)

    def __str__(self):
        return 'Banner %s' % self.name

    @property
    def next_time(self):
        now = timezone.now()
        if self.end_time < now:
            return 0
        return int(round((self.end_time - now).total_seconds()))
