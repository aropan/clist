import re

from django.db import models
from django.db.models import Q
from django.contrib.auth.models import User
from django.contrib.postgres.fields import JSONField, ArrayField
from datetime import timedelta
from django_countries.fields import CountryField
from phonenumber_field.modelfields import PhoneNumberField

from pyclist.models import BaseModel, BaseManager
from clist.models import Contest


class Coder(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    username = models.CharField(max_length=255, unique=True)
    first_name_native = models.CharField(max_length=255, blank=True)
    last_name_native = models.CharField(max_length=255, blank=True)
    middle_name_native = models.CharField(max_length=255, blank=True)
    organization = models.ForeignKey('Organization', null=True, blank=True, on_delete=models.SET_NULL)
    timezone = models.CharField(max_length=32, default="UTC")
    settings = JSONField(default=dict, blank=True)
    country = CountryField(null=True, blank=True)
    phone_number = PhoneNumberField(blank=True)

    def __str__(self):
        return "%s" % (self.username)

    def save(self, *args, **kwargs):
        self.username = self.user.username
        return super().save(*args, **kwargs)

    @property
    def chat(self):
        if not hasattr(self, 'cchat'):
            self.cchat = list(self.chat_set.exclude(secret_key__isnull=True))
        return self.cchat[0] if self.cchat else None

    def get_contest_filter(self, categories, ignores=None):
        filter_categories = Q()
        if not isinstance(categories, (list, tuple, set)):
            categories = (categories, )
        for c in categories:
            filter_categories |= Q(categories__contains=[c])
        if ignores:
            filter_categories &= ~Q(id__in=ignores)

        hide = Q()
        show = Q()
        for filter_ in self.filter_set.filter(filter_categories):
            query = Q()
            if filter_.resources:
                query &= Q(resource__id__in=filter_.resources)
            if filter_.duration_from:
                seconds = timedelta(minutes=filter_.duration_from).total_seconds()
                query &= Q(duration_in_secs__gte=seconds)
            if filter_.duration_to:
                seconds = timedelta(minutes=filter_.duration_to).total_seconds()
                query &= Q(duration_in_secs__lte=seconds)
            if filter_.regex:
                field = 'title'
                regex = filter_.regex

                match = re.search(r'^(?P<field>[a-z]+):(?P<sep>.)(?P<regex>.+)(?P=sep)$', filter_.regex)
                if match:
                    f = match.group('field')
                    if f in ('url',):
                        field = f
                        regex = match.group('regex')
                query_regex = Q(**{f'{field}__regex': regex})
                if filter_.inverse_regex:
                    query_regex = ~query_regex
                query &= query_regex
            if filter_.contest_id:
                query &= Q(pk=filter_.contest_id)

            if filter_.to_show:
                show |= query
            else:
                hide |= query
        result = ~hide & show
        return result

    def get_categories(self):
        categories = list(Filter.CATEGORIES)
        for chat in self.chat_set.filter(secret_key__isnull=True):
            categories.append(chat.get_group_name())
        return categories

    def get_tshirt_size(self):
        p = self.participant_set.order_by('-modified').first()
        return p.tshirt_size_value if p is not None else None

    def account_set_order_by_pk(self):
        return self.account_set.order_by('pk')

    @property
    def ordered_filter_set(self):
        return self.filter_set.order_by('created')


class PartyManager(BaseManager):
    def for_user(self, user):
        filt = Q(is_hidden=False)
        if user.is_authenticated:
            filt |= Q(author=user.coder) | Q(pk__in=user.coder.party_set.filter(is_hidden=True))
        return self.get_queryset().filter(filt)


class Party(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255)
    coders = models.ManyToManyField(Coder, blank=True)
    secret_key = models.CharField(max_length=20, blank=True, null=True)
    author = models.ForeignKey(Coder, related_name='party_author_set', on_delete=models.CASCADE)
    is_hidden = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.secret_key:
            self.secret_key = User.objects.make_random_password(length=20)
        return super(Party, self).save(*args, **kwargs)

    def __str__(self):
        return self.name

    def has_permission_toggle_contests(self, coder):
        return self.author == coder

    class Meta:
        verbose_name_plural = 'Parties'

    objects = PartyManager()


def _get_default_categories():
    return ['list', 'calendar', 'email', 'telegram', 'api']


class Filter(BaseModel):
    CATEGORIES = ['list', 'calendar', 'email', 'telegram', 'api']

    coder = models.ForeignKey(Coder, on_delete=models.CASCADE)
    name = models.CharField(max_length=60, null=True, blank=True)
    duration_from = models.IntegerField(null=True, blank=True)
    duration_to = models.IntegerField(null=True, blank=True)
    regex = models.CharField(max_length=1000, null=True, blank=True)
    inverse_regex = models.BooleanField(default=False)
    to_show = models.BooleanField(default=True)
    resources = JSONField(default=list, blank=True)
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE, default=None, null=True, blank=True)
    categories = ArrayField(models.CharField(max_length=20), blank=True, default=_get_default_categories)

    def __str__(self):
        result = '' if not self.name else '{0.name}: '.format(self)
        result += '{0.coder}, {0.resources} resources, {0.contest} contest'.format(self)
        if self.duration_from is not None or self.duration_to is not None:
            result += ', duration'
            if self.duration_from is not None:
                result += ' from {0.duration_from}'.format(self)
            if self.duration_to is not None:
                result += ' to {0.duration_to}'.format(self)
        if self.regex is not None:
            result += ', regex '
            if self.inverse_regex:
                result += '!'
            result += '= ' + self.regex
        return result

    def dict(self):
        ret = {
            "name": self.name,
            "id": self.id,
            "duration": {
                "from": self.duration_from or "",
                "to": self.duration_to or "",
            },
            "regex": self.regex or "",
            "resources": self.resources,
            "contest": self.contest_id,
            "categories": self.categories,
            "inverse_regex": self.inverse_regex,
            "to_show": self.to_show,
        }
        if self.contest_id:
            ret['contest__title'] = self.contest.title
        return ret


class Organization(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    abbreviation = models.CharField(max_length=32, blank=True, null=True)
    name_ru = models.CharField(max_length=255, unique=True)
    author = models.ForeignKey(
        Coder,
        related_name='organization_author_set',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return "%s" % (self.name)
