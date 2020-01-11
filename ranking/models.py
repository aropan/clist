import re

from pyclist.models import BaseModel
from django.db import models
from django.dispatch import receiver
from true_coders.models import Coder, Party
from clist.models import Contest, Resource
from django.contrib.postgres.fields import JSONField
from django_countries.fields import CountryField


class Account(BaseModel):
    coders = models.ManyToManyField(Coder, blank=True)
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    key = models.CharField(max_length=1024, null=False, blank=False)
    name = models.CharField(max_length=1024, null=True, blank=True)
    country = CountryField(null=True, blank=True)
    info = JSONField(default=dict, blank=True)
    updated = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return '%s on %s' % (str(self.key), str(self.resource))

    def dict(self):
        return {
            'account': self.key,
            'resource': self.resource.host,
            'name': self.name,
        }

    class Meta:
        unique_together = ('resource', 'key')


class Rating(BaseModel):
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
    party = models.ForeignKey(Party, on_delete=models.CASCADE)

    def __str__(self):
        return 'rating %s by %s' % (str(self.party.name), str(self.contest.title))


class Statistics(BaseModel):
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
    place = models.CharField(max_length=17, default=None, null=True, blank=True)
    place_as_int = models.IntegerField(default=None, null=True, blank=True)
    solving = models.FloatField(default=0, blank=True)
    upsolving = models.FloatField(default=0, blank=True)
    addition = JSONField(default=dict, blank=True)
    url = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return f'{self.account_id} on {self.contest_id} = {self.solving} + {self.upsolving}'

    class Meta:
        verbose_name_plural = 'Statistics'
        unique_together = ('account', 'contest')

        indexes = [
            models.Index(fields=['place_as_int', '-solving']),
        ]


@receiver(models.signals.pre_save, sender=Statistics)
def statistics_pre_save(sender, instance, *args, **kwargs):
    instance.place_as_int = None
    if instance.place is not None:
        match = re.search('[0-9]+', str(instance.place))
        if match:
            instance.place_as_int = int(match.group(0))


class Module(BaseModel):
    resource = models.OneToOneField(Resource, on_delete=models.CASCADE)
    path = models.CharField(max_length=255)
    min_delay_after_end = models.DurationField()
    max_delay_after_end = models.DurationField()
    delay_on_error = models.DurationField()
    delay_on_success = models.DurationField(null=True, blank=True)
    multi_account_allowed = models.BooleanField(default=False)
    has_accounts_infos_update = models.BooleanField(default=False)

    def __str__(self):
        return '%s: %s' % (self.resource.host, self.path)
