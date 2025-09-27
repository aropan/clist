import re
import uuid
from datetime import timedelta

from django.db import models
from django.utils import timezone

from clist.templatetags.extras import as_number
from my_oauth.utils import refresh_acccess_token
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
    state_field = models.CharField(max_length=255, default="state")
    email_field = models.CharField(max_length=255, default="email")
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
        unique_together = (
            "service",
            "user_id",
        )

    def __str__(self):
        return f"{self.user_id} on {self.service} Token#{self.id}"

    def email_hint(self):
        login, domain = self.email.split("@")

        def hint(s):
            regex = "(?<!^)."
            if len(s) > 3:
                regex += "(?!$)"
            return re.sub(regex, ".", s)

        return f"{hint(login)}@{hint(domain)}"

    def update_expires_at(self, expires_in, force: bool = False):
        expires_in = as_number(expires_in, force=True)
        if expires_in is None:
            if force:
                self.expires_at = None
            return
        expires_at = timezone.now() + timedelta(seconds=expires_in)
        if self.expires_at == expires_at:
            return
        self.expires_at = expires_at

    def get_access_token(self):
        if self.expires_at and self.expires_at < timezone.now():
            self.access_token.update(refresh_acccess_token(self))
            self.update_expires_at(self.access_token.get("expires_in"), force=True)
            self.save(update_fields=["access_token", "expires_at"])
        return self.access_token["access_token"]


class Form(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    title = models.CharField(max_length=255, default=None)
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    code = models.TextField()
    service_code_args = models.TextField(blank=True)
    secret = models.CharField(max_length=64, default=generate_secret_64, blank=True, unique=True)
    registration = models.BooleanField(default=False)
    register_url = models.URLField(null=True, blank=True)
    register_headers = models.TextField(null=True, blank=True)
    grant_credentials = models.BooleanField(default=False)
    approved_code = models.TextField(null=True, blank=True)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.title:
            self.title = self.name
        if not self.secret:
            self.secret = generate_secret_64()
        super().save(*args, **kwargs)

    def is_coming(self):
        return self.start_time is not None and timezone.now() < self.start_time

    def is_closed(self):
        return self.end_time is not None and self.end_time < timezone.now()

    def __str__(self):
        return f"{self.name} Form#{self.id}"


class Credential(BaseModel):

    class State(models.IntegerChoices):
        UNASSIGNED = 1, "Unassigned"
        ASSIGNED = 2, "Assigned"
        APPROVED = 3, "Approved"

    form = models.ForeignKey(Form, on_delete=models.CASCADE)
    login = models.CharField(max_length=255)
    password = models.CharField(max_length=255)
    state = models.PositiveSmallIntegerField(choices=State.choices, default=State.UNASSIGNED, db_index=True)
    token = models.ForeignKey(Token, null=True, blank=True, on_delete=models.CASCADE)

    def is_approved(self):
        return self.state == self.State.APPROVED

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["form", "login"], name="unique_form_login"),
            models.UniqueConstraint(
                fields=["form", "token"],
                condition=models.Q(token__isnull=False),
                name="unique_form_token_not_null",
            ),
        ]

    def __str__(self):
        return f"{self.login} Credential#{self.id}"
