import re

from django.db import models
from django.contrib.postgres.fields import JSONField

from pyclist.models import BaseModel, BaseManager
from true_coders.models import Coder


class ActiveServiceManager(BaseManager):
    def get_queryset(self):
        return super(ActiveServiceManager, self).get_queryset().filter(disable=False)


class Service(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    title = models.CharField(max_length=255)
    app_id = models.CharField(max_length=255)
    secret = models.CharField(max_length=255)
    code_uri = models.TextField()
    token_uri = models.TextField()
    token_post = models.TextField(blank=True)
    state_field = models.CharField(max_length=255)
    user_id_field = models.CharField(max_length=255)
    data_uri = models.TextField()
    data_header = models.TextField(null=True, blank=True, default=None)
    fa_icon = models.CharField(max_length=255)
    disable = models.BooleanField(default=False)

    def __str__(self):
        return "%s" % (self.name)

    objects = BaseManager()
    active_objects = ActiveServiceManager()


class Token(BaseModel):
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    coder = models.ForeignKey(Coder, null=True, on_delete=models.CASCADE, blank=True)
    user_id = models.CharField(max_length=255)
    email = models.EmailField()
    access_token = JSONField(default=dict, blank=True)
    data = JSONField(default=dict, blank=True)

    tokens_view_time = models.DateTimeField(null=True, default=None, blank=True)
    n_viewed_tokens = models.PositiveSmallIntegerField(default=0, blank=True)

    class Meta:
        unique_together = ('service', 'user_id', )

    def __str__(self):
        return "%s on %s" % (self.coder, self.service)

    def email_hint(self):
        login, domain = self.email.split('@')

        def hint(s):
            regex = '(?<!^).'
            if len(s) > 3:
                regex += '(?!$)'
            return re.sub(regex, '.', s)

        return f'{hint(login)}@{hint(domain)}'
