from pyclist.models import BaseModel, BaseManager
from django.db import models
from datetime import timedelta
from django.utils import timezone
from jsonfield import JSONField


class Resource(BaseModel):
    host = models.CharField(max_length=255, unique=True)
    enable = models.BooleanField()
    url = models.CharField(max_length=255)
    regexp = models.CharField(max_length=1024, null=True, blank=True)
    path = models.CharField(max_length=255, null=True, blank=True)
    parse_url = models.CharField(max_length=255, null=True, blank=True)
    timezone = models.CharField(max_length=30, null=True, blank=True)
    color = models.CharField(max_length=20, null=True, blank=True)
    uid = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return "%s" % (self.host)


class VisibleContestManager(BaseManager):
    def get_queryset(self):
        return super(VisibleContestManager, self).get_queryset().filter(invisible=0)


class Contest(models.Model):
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
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
    info = JSONField(default={}, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    was_auto_added = models.BooleanField(default=False)

    objects = BaseManager()
    visible = VisibleContestManager()

    class Meta:
        unique_together = ('resource', 'key', )

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
    data = JSONField(default={}, blank=True)

    def __str__(self):
        return 'Banner %s' % self.name
