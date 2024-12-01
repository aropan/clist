import hashlib
import os
import re
from urllib.parse import quote, urljoin

import magic
import requests
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import models
from django.db.models import F, OuterRef, Q, Sum
from django.db.models.functions import Coalesce, Upper
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django_countries.fields import CountryField
from sql_util.utils import Exists, SubqueryCount, SubquerySum

from clist.models import Contest, Resource
from clist.templatetags.extras import get_item, has_season
from clist.utils import update_account_by_coders
from pyclist.indexes import ExpressionIndex, GistIndexTrgrmOps
from pyclist.models import BaseManager, BaseModel
from true_coders.models import Coder, Party

AVATAR_RELPATH_FIELD = 'avatar_relpath_'


class Account(BaseModel):
    coders = models.ManyToManyField(Coder, blank=True)
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    key = models.CharField(max_length=400, null=False, blank=False, db_index=True)
    name = models.CharField(max_length=400, null=True, blank=True, db_index=True)
    country = CountryField(null=True, blank=True, db_index=True)
    url = models.CharField(max_length=4096, null=True, blank=True)
    n_contests = models.IntegerField(default=0, db_index=True)
    n_writers = models.IntegerField(default=0, db_index=True)
    n_subscribers = models.IntegerField(default=0, db_index=True, blank=True)
    last_activity = models.DateTimeField(default=None, null=True, blank=True, db_index=True)
    last_submission = models.DateTimeField(default=None, null=True, blank=True, db_index=True)
    last_rating_activity = models.DateTimeField(default=None, null=True, blank=True, db_index=True)
    rating = models.IntegerField(default=None, null=True, blank=True, db_index=True)
    rating50 = models.SmallIntegerField(default=None, null=True, blank=True, db_index=True)
    resource_rank = models.IntegerField(null=True, blank=True, default=None, db_index=True)
    info = models.JSONField(default=dict, blank=True)
    updated = models.DateTimeField(auto_now_add=True)
    duplicate = models.ForeignKey('Account', null=True, blank=True, on_delete=models.CASCADE)
    global_rating = models.IntegerField(null=True, blank=True, default=None, db_index=True)
    need_verification = models.BooleanField(default=False)
    deleted = models.BooleanField(null=True, blank=True, default=None, db_index=True)
    try_renaming_check_time = models.DateTimeField(null=True, blank=True, default=None)
    try_fill_missed_ranks_time = models.DateTimeField(null=True, blank=True, default=None)
    rating_prediction = models.JSONField(default=None, null=True, blank=True)

    def __str__(self):
        return 'Account#%d %s on %s' % (self.pk, str(self.key), str(self.resource_id))

    def dict(self):
        return {
            'pk': self.pk,
            'account': self.key,
            'name': self.name,
        }

    def dict_with_info(self):
        ret = self.dict()
        ret.update(self.info.get('profile_url', {}))
        for k, v in ret.items():
            if isinstance(v, str):
                ret[k] = quote(v)
        return ret

    def avatar_url(self, resource=None):
        resource = resource or self.resource
        if resource.avatar_url:
            try:
                avatar_url_info = resource.info.get('avatar_url', {})
                fields = avatar_url_info.get('fields')
                if fields and any(not self.info.get(f) for f in fields):
                    return
                url = resource.avatar_url.format(key=self.key, info=self.info)
                if avatar_url_info.get('urljoin'):
                    url = urljoin(avatar_url_info.get('urljoin'), url)
                return url
            except KeyError:
                pass

    def profile_url(self, resource=None):
        resource = resource or self.resource
        info = self.dict_with_info()
        return resource.profile_url.format(**info)

    @staticmethod
    def is_special_info_field(field):
        if not field:
            return False
        if field[0] == '_' or field[-1] == '_' or '___' in field:
            return True
        if field in {'profile_url', 'rating', 'is_virtual'}:
            return True
        field = field.lower()
        if field in {'telegram', 'dateofbirth'}:
            return True
        if 'email' in field or 'password' in field:
            return True

    def get_last_season(self):
        if not self.last_activity:
            return
        date = self.last_activity
        year = date.year - (0 if date.month > 8 else 1)
        season = f'{year}-{year + 1}'
        return season

    def update_last_activity(self, statistic):
        if (
            statistic.last_activity and
            (not self.last_activity or self.last_activity < statistic.last_activity)
        ):
            self.last_activity = statistic.last_activity
            self.save(update_fields=['last_activity'])

    def update_last_rating_activity(self, statistic, contest=None, resource=None):
        contest = contest or statistic.contest
        resource = resource or contest.resource
        if (
            statistic.is_rated and statistic.last_activity and
            (not self.last_rating_activity or self.last_rating_activity < statistic.last_activity) and
            resource.is_major_kind(contest)
        ):
            self.last_rating_activity = statistic.last_activity
            self.save(update_fields=['last_rating_activity'])

    def display(self, with_resource=None):
        if not with_resource and self.name and has_season(self.key, self.name):
            ret = self.name
        elif not self.name or self.name == self.key:
            ret = self.key
        else:
            ret = f'{self.key}, {self.name}'
        if with_resource:
            ret += f', {self.resource.host}'
        return ret

    def short_display(self, resource=None, name=None):
        name = name or self.name
        resource = resource or self.resource
        name_instead_key = get_item(resource, 'info.standings.name_instead_key')
        name_instead_key = get_item(self, 'info._name_instead_key', default=name_instead_key)
        name_instead_key = name and (name_instead_key or has_season(self.key, name))
        return name if name_instead_key else self.key

    def account_default_url(self):
        return reverse('coder:account', args=[self.key, self.resource.host])

    def save(self, *args, **kwargs):
        update_fields = kwargs.get('update_fields')
        prev_rating = self.rating
        if self.deleted:
            self.rating = None
        elif 'rating' in self.info:
            if self.rating != self.info['rating']:
                self.resource.rating_update_time = timezone.now()
                self.resource.save(update_fields=['rating_update_time'])
            self.rating = self.info['rating']
            self.rating50 = self.rating / 50 if self.rating is not None else None
        if self.rating is None:
            self.rating50 = None
            self.resource_rank = None
        if update_fields and self.rating != prev_rating:
            update_fields.extend(['rating', 'rating50', 'resource_rank'])
        download_avatar_url(self)
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=['resource', 'name']),
            models.Index(fields=['resource', 'country']),

            GistIndexTrgrmOps(fields=['key']),
            GistIndexTrgrmOps(fields=['name']),
            ExpressionIndex(expressions=[Upper('key')]),

            models.Index(fields=['resource', 'rating']),
            models.Index(fields=['resource', '-rating']),
            models.Index(fields=['resource', 'rating50']),
            models.Index(fields=['resource', '-rating50']),
            models.Index(fields=['resource', 'last_activity']),
            models.Index(fields=['resource', '-last_activity']),
            models.Index(fields=['resource', 'n_contests']),
            models.Index(fields=['resource', '-n_contests']),
            models.Index(fields=['resource', 'n_writers']),
            models.Index(fields=['resource', '-n_writers']),
            models.Index(fields=['resource', 'updated']),
            models.Index(fields=['resource', '-updated']),
            models.Index(fields=['resource', 'resource_rank']),
            models.Index(fields=['resource', '-resource_rank']),

            models.Index(fields=['resource', 'country', '-rating']),
            models.Index(fields=['resource', 'country', '-rating50']),
            models.Index(fields=['resource', 'country', '-last_activity']),
            models.Index(fields=['resource', 'country', '-n_contests']),
            models.Index(fields=['resource', 'country', '-n_writers']),
            models.Index(fields=['resource', 'country', '-updated']),
            models.Index(fields=['resource', 'country', 'resource_rank']),
            models.Index(fields=['resource', 'country', '-resource_rank']),

            models.Index(fields=['country', '-rating']),
            models.Index(fields=['country', '-rating50']),
            models.Index(fields=['country', '-last_activity']),
            models.Index(fields=['country', '-n_contests']),
            models.Index(fields=['country', '-n_writers']),
            models.Index(fields=['country', '-updated']),
            models.Index(fields=['country', 'resource_rank']),
            models.Index(fields=['country', '-resource_rank']),
        ]

        unique_together = ('resource', 'key')


class CountryAccount(BaseModel):
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    country = CountryField(null=False, db_index=True)
    n_accounts = models.IntegerField(default=0, db_index=True)
    n_rating_accounts = models.IntegerField(default=0, db_index=True)
    rating = models.IntegerField(default=None, null=True, blank=True, db_index=True)
    resource_rank = models.IntegerField(null=True, blank=True, default=None, db_index=True)
    raw_rating = models.FloatField(default=None, null=True, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['resource', 'country']),
            models.Index(fields=['resource', 'rating', 'country']),
            models.Index(fields=['resource', '-rating', 'country']),
            models.Index(fields=['resource', 'resource_rank', 'country']),
            models.Index(fields=['resource', '-resource_rank', 'country']),
            models.Index(fields=['resource', 'n_accounts', 'country']),
            models.Index(fields=['resource', '-n_accounts', 'country']),
        ]

        unique_together = ('resource', 'country')


class AccountRenaming(BaseModel):
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    old_key = models.CharField(max_length=1024, null=False, blank=False)
    new_key = models.CharField(max_length=1024, null=True, blank=True)

    def __str__(self):
        return f'{self.old_key} -> {self.new_key}'

    class Meta:
        indexes = [
            GistIndexTrgrmOps(fields=['old_key']),
            GistIndexTrgrmOps(fields=['new_key']),
            models.Index(fields=['resource', 'old_key']),
            models.Index(fields=['resource', 'new_key']),
        ]

        unique_together = ('resource', 'old_key')


def download_avatar_url(account):
    download_avatar_url = account.info.pop('download_avatar_url_', None)
    if not download_avatar_url:
        return

    checksum_field = account.resource.info.get('standings', {}).get('download_avatar_checksum_field')
    if checksum_field:
        headers = requests.head(download_avatar_url).headers
        checksum_value = headers[checksum_field]
        checksum_field += '_'
        if checksum_value == account.info.get(checksum_field):
            return

    response = requests.get(download_avatar_url)
    if response.status_code != 200:
        return

    content_type = response.headers.get('Content-Type')
    if not content_type:
        content_type = magic.from_buffer(response.content, mime=True)
    ext = content_type.split('/')[-1]
    ext = ext.split('+')[0]
    folder = re.sub('[./]', '_', account.resource.host)
    hashname = hashlib.md5(download_avatar_url.encode()).hexdigest()
    hashname = hashname[:2] + '/' + hashname[2:4] + '/' + hashname[4:]
    relpath = os.path.join('avatars', folder, f'{hashname}.{ext}')
    filepath = os.path.join(settings.MEDIA_ROOT, relpath)

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'wb') as fo:
        fo.write(response.content)

    account.info[AVATAR_RELPATH_FIELD] = relpath
    if checksum_field:
        account.info[checksum_field] = checksum_value


@receiver(post_save, sender=Account)
@receiver(post_delete, sender=Account)
def count_resource_accounts(signal, instance, **kwargs):
    if signal is post_delete:
        instance.resource.n_accounts -= 1
        instance.resource.save(update_fields=['n_accounts'])
    elif signal is post_save and kwargs['created']:
        instance.resource.n_accounts += 1
        instance.resource.save(update_fields=['n_accounts'])


@receiver(pre_save, sender=Account)
@receiver(m2m_changed, sender=Account.coders.through)
def update_account_url(signal, instance, **kwargs):
    if kwargs.get('reverse'):
        return
    account = instance

    if signal is pre_save:
        if account.url:
            return
        account.url = account.account_default_url()
    elif signal is m2m_changed:
        action = kwargs.get('action')
        if not action or not action.startswith('post_'):
            return
        update_account_by_coders(account)


@receiver(m2m_changed, sender=Account.writer_set.through)
def update_account_writer(signal, instance, action, reverse, pk_set, **kwargs):
    when, action = action.split('_', 1)
    if when != 'post':
        return
    if action == 'add':
        delta = 1
    elif action == 'remove':
        delta = -1
    else:
        return

    if reverse:
        Account.objects.filter(pk=instance.pk).update(n_writers=F('n_writers') + delta)
    elif pk_set:
        Account.objects.filter(pk__in=pk_set).update(n_writers=F('n_writers') + delta)


@receiver(m2m_changed, sender=Account.coders.through)
def update_coder_n_accounts_and_n_contests(signal, instance, action, reverse, pk_set, **kwargs):
    if action not in ['post_add', 'post_remove']:
        return

    if reverse:
        instance.n_accounts = instance.account_set.count()
        instance.n_contests = instance.account_set.aggregate(total=Sum('n_contests'))['total'] or 0
        instance.save(update_fields=['n_accounts', 'n_contests'])

        resources = Resource.objects.annotate(has_account=Exists('account', filter=Q(pk__in=pk_set)))
        resources = resources.filter(has_account=True)
        resources = list(resources.values_list('host', flat=True))
        coders = [instance.username]
    else:
        Coder.objects.filter(pk__in=pk_set) \
            .annotate(n_a=SubqueryCount('account')) \
            .annotate(n_c=SubquerySum('account__n_contests')) \
            .update(n_accounts=F('n_a'), n_contests=Coalesce('n_c', 0))

        coders = list(Coder.objects.filter(pk__in=pk_set).values_list('username', flat=True))
        resources = [instance.resource.host]

    if coders and resources:
        call_command('set_coder_problems', coders=coders, resources=resources)


class AccountVerification(BaseModel):
    coder = models.ForeignKey(Coder, on_delete=models.CASCADE)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    code = models.CharField(max_length=10)

    class Meta:
        unique_together = ('coder', 'account')

    def text(self):
        return f'ClistCheckCode{self.code}'


class VerifiedAccount(BaseModel):
    coder = models.ForeignKey(Coder, on_delete=models.CASCADE, related_name='verified_accounts')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='verified_accounts')

    class Meta:
        unique_together = ('coder', 'account')


@receiver(pre_save, sender=AccountVerification)
def account_verification_pre_save(sender, instance, *args, **kwargs):
    if not instance.code:
        instance.code = get_random_string(length=10)


class Rating(BaseModel):
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE, related_name='ratings')
    party = models.ForeignKey(Party, on_delete=models.CASCADE)

    def __str__(self):
        return 'rating %s by %s' % (str(self.party.name), str(self.contest.title))

    class Meta:
        unique_together = ('contest', 'party')


class AutoRating(BaseModel):
    party = models.ForeignKey(Party, on_delete=models.CASCADE)
    info = models.JSONField(default=dict, blank=True)
    deadline = models.DateTimeField()

    def __str__(self):
        return 'auto rating [%d] with party [%d]' % (self.pk, self.party_id)


class Statistics(BaseModel):
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
    place = models.CharField(max_length=17, default=None, null=True, blank=True)
    place_as_int = models.IntegerField(default=None, null=True, blank=True)
    solving = models.FloatField(default=0, blank=True)
    upsolving = models.FloatField(default=0, blank=True)
    addition = models.JSONField(default=dict, blank=True)
    url = models.TextField(null=True, blank=True)
    new_global_rating = models.IntegerField(null=True, blank=True, default=None, db_index=True)
    global_rating_change = models.IntegerField(null=True, blank=True, default=None)
    skip_in_stats = models.BooleanField(default=False)
    advanced = models.BooleanField(default=False)
    last_activity = models.DateTimeField(default=None, null=True, blank=True, db_index=True)
    rating_prediction = models.JSONField(default=None, null=True, blank=True)

    @staticmethod
    def is_special_addition_field(field):
        if not field:
            return False
        if field[0] == '_' or field[-1] == '_':
            return True
        return field in settings.ADDITION_HIDE_FIELDS_

    def __str__(self):
        return f'Statistics#{self.id} account#{self.account_id} on contest#{self.contest_id}'

    def get_old_rating(self, use_rating_prediction=True):
        rating_datas = [self.addition]
        if use_rating_prediction:
            rating_datas.append(self.rating_prediction)
        for rating_data in rating_datas:
            if not rating_data:
                continue
            if 'old_rating' in rating_data:
                return rating_data['old_rating']
            if 'new_rating' in rating_data and 'rating_change' in rating_data:
                return rating_data['new_rating'] - rating_data['rating_change']

    @property
    def is_rated(self):
        if self.skip_in_stats:
            return False
        return 'new_rating' in self.addition or 'rating_change' in self.addition

    @property
    def account_name(self):
        resource = (
            self.fetched_field('contest__resource') or
            self.fetched_field('account__resource') or
            self.contest.resource
        )
        return self.account.short_display(resource=resource, name=self.addition.get('name'))

    @classmethod
    def top_n_filter(cls, n):
        return Q(place_as_int__lte=n)

    @classmethod
    def first_ac_filter(cls):
        return Q(addition__problems__icontains='"first_ac": true')

    class Meta:
        verbose_name_plural = 'Statistics'
        unique_together = ('account', 'contest')

        indexes = [
            models.Index(fields=['place_as_int', 'created']),
            models.Index(fields=['place_as_int', '-solving']),
            models.Index(fields=['place_as_int', '-created']),
            models.Index(fields=['contest', 'place_as_int', '-solving', 'id']),
            models.Index(fields=['contest', 'account']),
            models.Index(fields=['contest', 'advanced', 'place_as_int']),
            models.Index(fields=['contest', 'account', 'advanced', 'place_as_int']),
            models.Index(fields=['account', 'advanced']),
            models.Index(fields=['account', 'skip_in_stats']),
        ]


@receiver(post_save, sender=Statistics)
@receiver(post_delete, sender=Statistics)
def count_account_contests(signal, instance, **kwargs):
    if instance.skip_in_stats:
        return

    if signal is post_delete:
        instance.account.n_contests -= 1
        instance.account.save(update_fields=['n_contests'])
    elif signal is post_save:
        if kwargs['created']:
            instance.account.n_contests += 1
            instance.account.save(update_fields=['n_contests'])

        instance.account.update_last_activity(statistic=instance)
        instance.account.update_last_rating_activity(statistic=instance)


class Module(BaseModel):
    resource = models.OneToOneField(Resource, on_delete=models.CASCADE)
    path = models.CharField(max_length=255)
    enable = models.BooleanField(default=True, blank=True, db_index=True)
    min_delay_after_end = models.DurationField(null=True, blank=True)
    max_delay_after_end = models.DurationField()
    delay_on_error = models.DurationField()
    delay_on_success = models.DurationField(null=True, blank=True)
    long_contest_idle = models.DurationField(default='06:00:00', blank=True)
    long_contest_divider = models.IntegerField(default=15)
    shortly_after = models.DurationField(default='00:30:00', blank=True)
    delay_shortly_after = models.DurationField(default='00:05:00', blank=True)

    class BaseModuleManager(BaseManager):
        def get_queryset(self):
            return super().get_queryset().select_related('resource')

    objects = BaseModuleManager()

    def __str__(self):
        return f'{self.resource.host} Module#{self.id}'


class StageContest(BaseModel):
    stage = models.ForeignKey('ranking.Stage', on_delete=models.CASCADE)
    contest = models.ForeignKey('clist.Contest', on_delete=models.CASCADE)


class Stage(BaseModel):
    contest = models.OneToOneField(Contest, on_delete=models.CASCADE)
    filter_params = models.JSONField(default=dict, blank=True)
    score_params = models.JSONField(default=dict, blank=True)
    contests = models.ManyToManyField(Contest, related_name='stages', through='StageContest', blank=True)

    def __str__(self):
        return 'Stage#%d %s' % (self.pk, self.contest)


class VirtualStart(BaseModel):
    coder = models.ForeignKey(Coder, on_delete=models.CASCADE, related_name='virtual_starts')

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    entity = GenericForeignKey('content_type', 'object_id')

    start_time = models.DateTimeField()
    finish_time = models.DateTimeField(default=None, null=True, blank=True)

    addition = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ('coder', 'content_type', 'object_id')
        indexes = [models.Index(fields=['coder', 'content_type', 'object_id'])]

    @classmethod
    def filter_by_content_type(cls, model_class):
        content_type = ContentType.objects.get_for_model(model_class)
        return cls.objects.filter(content_type=content_type)

    @staticmethod
    def contests_filter(coder):
        has_virtual_start = VirtualStart.filter_by_content_type(Contest).filter(coder=coder, object_id=OuterRef('id'))
        has_verdict = coder.verdicts.filter(problem__contests=OuterRef('pk'))
        return Exists(has_virtual_start) | Exists(has_verdict)

    def is_active(self):
        return self.finish_time is None or self.finish_time > timezone.now()

    def statistics(self):
        return [{
            'id': f'virtualstart{self.pk}',
            'contest_id': self.object_id if self.content_type.model == 'contest' else None,
            'place': self.addition.get('place'),
            'solving': self.addition.get('solving'),
            'addition': self.addition,
            'virtual_start': True,
            'virtual_start_pk': self.pk,
        }]


class MatchingStatus(models.TextChoices):
    NEW = 'new', 'New'
    PENDING = 'pending', 'Pending'
    SKIP = 'skip', 'Skip'
    ALREADY = 'already', 'Already'
    DONE = 'done', 'Done'
    ERROR = 'error', 'Error'


class AccountMatching(BaseModel):
    name = models.CharField(max_length=400)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    statistic = models.ForeignKey(Statistics, on_delete=models.CASCADE)
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE, related_name='account_matchings')
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    n_found_accounts = models.IntegerField(default=None, null=True, blank=True)
    n_found_coders = models.IntegerField(default=None, null=True, blank=True)
    n_different_coders = models.IntegerField(default=None, null=True, blank=True)
    coder = models.ForeignKey(Coder, default=None, blank=True, null=True, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=MatchingStatus.choices, default=MatchingStatus.NEW)

    class Meta:
        unique_together = ('name', 'statistic')

    def __str__(self):
        return f'AccountMatching#{self.pk} {self.name} statistic#{self.statistic_id}'


class ParseStatistics(BaseModel):
    contest = models.OneToOneField(Contest, on_delete=models.CASCADE, related_name='live_statistics')
    delay = models.DurationField(null=True, blank=True)
    parse_time = models.DateTimeField(null=True, blank=True)
    enable = models.BooleanField(default=True, blank=True)
    without_set_coder_problems = models.BooleanField(default=True, blank=True)
    without_stage = models.BooleanField(default=True, blank=True)
    without_subscriptions = models.BooleanField(default=False, blank=True)

    class Meta:
        verbose_name_plural = 'ParseStatistics'

    @staticmethod
    def relevant_contest():
        contests = Contest.objects.filter(parsestatistics__isnull=False, end_time__gt=timezone.now())
        return contests.order_by('end_time').first()

    def __str__(self):
        return f'ParseStatistics#{self.pk} contest#{self.contest_id}'
