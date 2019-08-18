from pyclist.models import BaseModel
from django.db import models
from true_coders.models import Coder, Party
from clist.models import Contest, Resource
from django.contrib.postgres.fields import JSONField


class Account(BaseModel):
    coders = models.ManyToManyField(Coder, blank=True)
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    key = models.CharField(max_length=1024, null=False, blank=False)

    def __str__(self):
        return '%s on %s' % (str(self.key), str(self.resource))

    def dict(self):
        return {
            'account': self.key,
            'resource': self.resource.host,
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
    solving = models.FloatField(default=0, blank=True)
    upsolving = models.FloatField(default=0, blank=True)
    addition = JSONField(default=dict, blank=True)
    url = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return '%s = %d + %d' % (
            self.account,
            self.solving,
            self.upsolving,
        )

    class Meta:
        verbose_name_plural = 'Statistics'
        unique_together = ('account', 'contest')


class Module(BaseModel):
    resource = models.OneToOneField(Resource, on_delete=models.CASCADE)
    path = models.CharField(max_length=255)
    min_delay_after_end = models.DurationField()
    max_delay_after_end = models.DurationField()
    delay_on_error = models.DurationField()
    delay_on_success = models.DurationField(null=True, blank=True)
    multi_account_allowed = models.BooleanField(default=False)

    def __str__(self):
        return '%s: %s' % (self.resource.host, self.path)
