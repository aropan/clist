import colorsys
from urllib.parse import urlparse
from datetime import timedelta

from django.db import models
from django.utils import timezone
from django.contrib.postgres.fields import JSONField

from pyclist.models import BaseModel, BaseManager


class Resource(BaseModel):
    host = models.CharField(max_length=255, unique=True)
    enable = models.BooleanField()
    url = models.CharField(max_length=255)
    regexp = models.CharField(max_length=1024, null=True, blank=True)
    path = models.CharField(max_length=255, null=True, blank=True)
    parse_url = models.CharField(max_length=255, null=True, blank=True)
    timezone = models.CharField(max_length=30, null=True, blank=True)
    color = models.CharField(max_length=20, null=True, blank=True)
    profile_url = models.CharField(max_length=255, null=True, blank=True, default=None)
    uid = models.CharField(max_length=100, null=True, blank=True)
    info = JSONField(default=dict, blank=True)
    ratings = JSONField(default=list, blank=True)
    has_rating_history = models.BooleanField(default=False)

    RATING_FIELDS = ('old_rating', 'OldRating', 'new_rating', 'NewRating', 'rating', 'Rating')

    def __str__(self):
        return "%s" % (self.host)

    def href(self):
        return '{uri.scheme}://{host}/'.format(uri=urlparse(self.url), host=self.host)

    def get_rating_color(self, value):
        if not self.ratings or value is None:
            return

        if isinstance(value, (list, tuple)):
            for v in value:
                ret = self.get_rating_color(v)
                if ret:
                    return ret
        elif isinstance(value, dict):
            for field in self.RATING_FIELDS:
                if field in value:
                    ret = self.get_rating_color(value.get(field))
                    if ret:
                        return ret
        else:
            if isinstance(value, str):
                value = int(value)
            for rating in self.ratings:
                if rating['low'] <= value <= rating['high']:
                    return rating

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

        super().save(*args, **kwargs)


class VisibleContestManager(BaseManager):
    def get_queryset(self):
        return super(VisibleContestManager, self).get_queryset().filter(invisible=0)


class Contest(models.Model):
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    title = models.CharField(max_length=2048)
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

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    was_auto_added = models.BooleanField(default=False)

    objects = BaseManager()
    visible = VisibleContestManager()

    class Meta:
        unique_together = ('resource', 'key', )

        indexes = [
            models.Index(fields=['start_time']),
            models.Index(fields=['end_time']),
        ]

    def save(self, *args, **kwargs):
        if self.duration_in_secs is None:
            self.duration_in_secs = (self.end_time - self.start_time).total_seconds()
        return super(Contest, self).save(*args, **kwargs)

    def is_over(self):
        return self.end_time <= timezone.now()

    def is_running(self):
        return not self.is_over() and self.start_time < timezone.now()

    def is_coming(self):
        return timezone.now() < self.start_time

    @property
    def next_time(self):
        if self.is_over():
            return 0
        return int(round(
            ((
                self.end_time
                if self.is_running()
                else self.start_time
            ) - timezone.now()).total_seconds()
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


class TimingContest(BaseModel):
    contest = models.OneToOneField(Contest, related_name='timing', on_delete=models.CASCADE)
    notification = models.DateTimeField(auto_now_add=True)
    statistic = models.DateTimeField(default=None, null=True)

    def __str__(self):
        return '%s timing, modified = %s' % (str(self.contest), self.modified)


class Banner(BaseModel):
    name = models.CharField(max_length=255)
    url = models.URLField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    template = models.CharField(max_length=255)
    data = JSONField(default=dict, blank=True)

    def __str__(self):
        return 'Banner %s' % self.name
