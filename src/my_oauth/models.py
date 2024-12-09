import re
import uuid

from django.db import models
from django.utils import timezone

from pyclist.models import BaseManager, BaseModel
from true_coders.models import Coder
from utils.strings import generate_secret_64


class ActiveServiceManager(BaseManager):
    def get_queryset(self):
        return super().get_queryset().filter(disable=False)


class Service(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    title = models.CharField(max_length=255)
    app_id = models.CharField(max_length=255)
    secret = models.CharField(max_length=255)
    code_uri = models.TextField()
    code_args = models.TextField(blank=True)
    token_uri = models.TextField()
    token_post = models.TextField(blank=True)
    refresh_token_uri = models.TextField(null=True, blank=True)
    refresh_token_post = models.TextField(null=True, blank=True)
    state_field = models.CharField(max_length=255, default='state')
    email_field = models.CharField(max_length=255, default='email')
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
    email = models.EmailField(null=True, blank=True)
    access_token = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)

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


class Form(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    code = models.TextField()
    service_code_args = models.TextField(blank=True)
    secret = models.CharField(max_length=64, default=generate_secret_64, blank=True, unique=True)
    register_url = models.URLField(null=True, blank=True)
    register_headers = models.TextField(null=True, blank=True)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)

    def is_coming(self):
        return self.start_time is not None and timezone.now() < self.start_time

    def is_closed(self):
        return self.end_time is not None and self.end_time < timezone.now()
