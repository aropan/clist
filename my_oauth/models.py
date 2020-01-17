import re

from pyclist.models import BaseModel
from django.db import models
from true_coders.models import Coder


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
    fa_icon = models.CharField(max_length=255)

    def __str__(self):
        return "%s" % (self.name)


class Token(BaseModel):
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    coder = models.ForeignKey(Coder, null=True, on_delete=models.CASCADE, blank=True)
    user_id = models.CharField(max_length=255)
    email = models.EmailField()

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
