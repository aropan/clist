import hashlib
import itertools
import os
import re
from typing import Optional
from urllib.parse import quote, urljoin

import magic
import requests
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import models
from django.db.models import F, OuterRef, Prefetch, Q, Sum
from django.db.models.functions import Coalesce, Upper
from django.db.models.signals import m2m_changed, post_delete, post_init, post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django_countries.fields import CountryField
from sql_util.utils import Exists, SubqueryCount, SubquerySum

from clist.models import Contest, Resource
from clist.templatetags.extras import get_item, get_statistic_stats, has_season
from clist.utils import update_account_by_coders
from pyclist.indexes import DescNullsLastIndex, ExpressionIndex, GistIndexTrgrmOps
from pyclist.models import BaseManager, BaseModel
from ranking.enums import AccountType
from true_coders.models import Coder, Party
from utils.mathutils import sum_with_none
from utils.signals import update_n_field_on_change

AVATAR_RELPATH_FIELD = 'avatar_relpath_'


class PriorityAccountManager(BaseManager):
    def get_queryset(self):
        return super().get_queryset().order_by('deleted', '-n_contests')


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
    n_listvalues = models.IntegerField(default=0, db_index=True, blank=True)
    last_activity = models.DateTimeField(default=None, null=True, blank=True, db_index=True)
    last_submission = models.DateTimeField(default=None, null=True, blank=True, db_index=True)
    last_rating_activity = models.DateTimeField(default=None, null=True, blank=True, db_index=True)
    rating = models.IntegerField(default=None, null=True, blank=True, db_index=True)
    rating50 = models.SmallIntegerField(default=None, null=True, blank=True, db_index=True)
    rating_update_time = models.DateTimeField(default=None, null=True, blank=True)
    resource_rank = models.IntegerField(null=True, blank=True, default=None, db_index=True)
    info = models.JSONField(default=dict, blank=True)
    submissions_info = models.JSONField(default=dict, blank=True)
    updated = models.DateTimeField(auto_now_add=True)
    duplicate = models.ForeignKey('Account', null=True, blank=True, on_delete=models.CASCADE)
    related = models.ForeignKey('Account', null=True, blank=True, on_delete=models.CASCADE,
                                related_name='related_accounts')
    global_rating = models.IntegerField(null=True, blank=True, default=None, db_index=True)
    need_verification = models.BooleanField(default=False)
    deleted = models.BooleanField(null=True, blank=True, default=None, db_index=True)
    try_renaming_check_time = models.DateTimeField(null=True, blank=True, default=None)
    try_fill_missed_ranks_time = models.DateTimeField(null=True, blank=True, default=None)
    rating_prediction = models.JSONField(default=None, null=True, blank=True)
    solving = models.FloatField(default=0, blank=True)
    upsolving = models.FloatField(default=None, null=True, blank=True)
    total_solving = models.FloatField(default=0, blank=True)
    n_solved = models.IntegerField(default=0, blank=True)
    n_upsolved = models.IntegerField(default=None, null=True, blank=True)
    n_total_solved = models.IntegerField(default=0, blank=True)
    n_first_ac = models.IntegerField(default=0, blank=True)
    n_win = models.IntegerField(default=None, null=True, blank=True)
    n_gold = models.IntegerField(default=None, null=True, blank=True)
    n_silver = models.IntegerField(default=None, null=True, blank=True)
    n_bronze = models.IntegerField(default=None, null=True, blank=True)
    n_medals = models.IntegerField(default=None, null=True, blank=True)
    n_other_medals = models.IntegerField(default=None, null=True, blank=True)
    n_first_places = models.IntegerField(default=None, null=True, blank=True)
    n_second_places = models.IntegerField(default=None, null=True, blank=True)
    n_third_places = models.IntegerField(default=None, null=True, blank=True)
    n_top_ten_places = models.IntegerField(default=None, null=True, blank=True)
    n_places = models.IntegerField(default=None, null=True, blank=True)
    account_type = models.PositiveSmallIntegerField(choices=AccountType.choices, default=AccountType.USER)

    objects = BaseManager()
    priority_objects = PriorityAccountManager()

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
        if field in {'profile_url', 'rating', 'raw_rating', 'is_virtual', 'is_team', 'name', 'country',
                     'rank_percentile'}:
            return True
        field = field.lower()
        for word in ('email', 'password', 'phone', 'birth', 'telegram'):
            if word in field:
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
        resource = resource or statistic.fetched_field('resource') or contest.resource
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

    @staticmethod
    def apply_coder_kind(queryset, coder_kind, logger=None):
        if not coder_kind or coder_kind == 'all':
            return queryset
        if coder_kind == 'real':
            coders = Coder.objects.filter(is_virtual=False, account=OuterRef('pk'))
        elif coder_kind == 'ghost' or coder_kind == 'virtual':
            coders = Coder.objects.filter(is_virtual=True, account=OuterRef('pk'))
        elif coder_kind == 'none':
            return queryset.filter(coders=None)
        else:
            if logger:
                logger.warning(f'Unknown coder kind: {coder_kind}')
            return queryset
        queryset = queryset.annotate(coder_kinds=Exists(coders)).filter(coder_kinds=True)
        return queryset

    def save(self, *args, **kwargs):
        update_fields = []
        if self.has_field('rating'):
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
            if self.rating != prev_rating:
                update_fields.extend(['rating', 'rating50', 'resource_rank'])
        if self.has_field('info'):
            download_avatar_url(self)

        account_type = None
        if self.info.get('is_university'):
            account_type = AccountType.UNIVERSITY
        elif self.info.get('is_team'):
            account_type = AccountType.TEAM
        if account_type and self.account_type != account_type:
            self.account_type = account_type
            update_fields.append('account_type')

        if update_fields:
            self.add_to_update_fields(update_fields, kwargs.get('update_fields'))

        super().save(*args, **kwargs)

    @staticmethod
    def get(resource, key) -> Optional['Account']:
        account = resource.account_set.filter(key=key).first()
        if (
            account is None and
            (renaming := resource.accountrenaming_set.filter(old_key=key).first())
        ):
            account = resource.account_set.get(key=renaming.new_key)
        return account

    @staticmethod
    def get_type(name) -> Optional[AccountType]:
        if not name or not isinstance(name, str):
            return None
        name_ci = name.upper()
        if name_ci not in AccountType.__members__:
            return None
        return AccountType[name_ci]

    @staticmethod
    def get_type_value(index) -> Optional[str]:
        for idx, value in AccountType.choices:
            if idx == index:
                return value.lower()
        return None

    def related_accounts_list(self):
        ret = self.related_accounts.all()
        if self.related:
            ret = itertools.chain([self.related], ret)
        return ret

    class Meta:
        indexes = [
            models.Index(fields=['resource']),
            models.Index(fields=['resource', 'name']),
            models.Index(fields=['resource', 'country']),
            models.Index(fields=['resource', 'updated'], condition=Q(updated__isnull=False), name="account_updated"),

            GistIndexTrgrmOps(fields=['key']),
            GistIndexTrgrmOps(fields=['name']),
            ExpressionIndex(expressions=[Upper('key')]),
            ExpressionIndex(expressions=[F('resource'), Upper('key')]),

            DescNullsLastIndex(fields=['resource', 'rating']),
            DescNullsLastIndex(fields=['resource', '-rating']),
            DescNullsLastIndex(fields=['resource', 'rating50']),
            DescNullsLastIndex(fields=['resource', '-rating50']),
            DescNullsLastIndex(fields=['resource', 'last_activity']),
            DescNullsLastIndex(fields=['resource', '-last_activity']),
            DescNullsLastIndex(fields=['resource', 'last_rating_activity']),
            DescNullsLastIndex(fields=['resource', '-last_rating_activity']),
            DescNullsLastIndex(fields=['resource', 'last_submission']),
            DescNullsLastIndex(fields=['resource', '-last_submission']),
            DescNullsLastIndex(fields=['resource', 'n_contests']),
            DescNullsLastIndex(fields=['resource', '-n_contests']),
            DescNullsLastIndex(fields=['resource', 'n_writers']),
            DescNullsLastIndex(fields=['resource', '-n_writers']),
            DescNullsLastIndex(fields=['resource', 'updated']),
            DescNullsLastIndex(fields=['resource', '-updated']),
            DescNullsLastIndex(fields=['resource', 'resource_rank']),
            DescNullsLastIndex(fields=['resource', '-resource_rank']),
            DescNullsLastIndex(fields=['resource', 'total_solving']),
            DescNullsLastIndex(fields=['resource', '-total_solving']),
            DescNullsLastIndex(fields=['resource', 'n_total_solved']),
            DescNullsLastIndex(fields=['resource', '-n_total_solved']),
            DescNullsLastIndex(fields=['resource', 'n_first_ac']),
            DescNullsLastIndex(fields=['resource', '-n_first_ac']),

            DescNullsLastIndex(fields=['resource', 'country', '-rating']),
            DescNullsLastIndex(fields=['resource', 'country', '-rating50']),
            DescNullsLastIndex(fields=['resource', 'country', '-last_activity']),
            DescNullsLastIndex(fields=['resource', 'country', '-last_rating_activity']),
            DescNullsLastIndex(fields=['resource', 'country', '-last_submission']),
            DescNullsLastIndex(fields=['resource', 'country', '-n_contests']),
            DescNullsLastIndex(fields=['resource', 'country', '-n_writers']),
            DescNullsLastIndex(fields=['resource', 'country', '-updated']),
            DescNullsLastIndex(fields=['resource', 'country', 'resource_rank']),
            DescNullsLastIndex(fields=['resource', 'country', '-resource_rank']),
            DescNullsLastIndex(fields=['resource', 'country', '-total_solving']),
            DescNullsLastIndex(fields=['resource', 'country', '-n_total_solved']),
            DescNullsLastIndex(fields=['resource', 'country', '-n_first_ac']),

            DescNullsLastIndex(fields=['country', '-rating']),
            DescNullsLastIndex(fields=['country', '-rating50']),
            DescNullsLastIndex(fields=['country', '-last_activity']),
            DescNullsLastIndex(fields=['country', '-last_rating_activity']),
            DescNullsLastIndex(fields=['country', '-last_submission']),
            DescNullsLastIndex(fields=['country', '-n_contests']),
            DescNullsLastIndex(fields=['country', '-n_writers']),
            DescNullsLastIndex(fields=['country', '-updated']),
            DescNullsLastIndex(fields=['country', 'resource_rank']),
            DescNullsLastIndex(fields=['country', '-resource_rank']),
            DescNullsLastIndex(fields=['country', '-total_solving']),
            DescNullsLastIndex(fields=['country', '-n_total_solved']),
            DescNullsLastIndex(fields=['country', '-n_first_ac']),

            DescNullsLastIndex(fields=['resource',
                                       '-n_win', '-n_gold', '-n_silver', '-n_bronze', '-n_other_medals']),
            DescNullsLastIndex(fields=['resource',
                                       '-n_first_places', '-n_second_places', '-n_third_places', '-n_top_ten_places']),

            DescNullsLastIndex(fields=['resource', 'account_type']),
            DescNullsLastIndex(fields=['resource', 'country', 'account_type']),
            DescNullsLastIndex(fields=['resource', 'account_type', 'n_contests']),
            DescNullsLastIndex(fields=['resource', 'account_type', '-n_contests']),
            DescNullsLastIndex(fields=['resource', 'account_type', 'last_activity']),
            DescNullsLastIndex(fields=['resource', 'account_type', '-last_activity']),
            DescNullsLastIndex(fields=['resource', 'account_type',
                                       '-n_win', '-n_gold', '-n_silver', '-n_bronze', '-n_other_medals']),
            DescNullsLastIndex(fields=['resource', 'account_type',
                                       '-n_first_places', '-n_second_places', '-n_third_places', '-n_top_ten_places']),
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
    n_win = models.IntegerField(default=None, null=True, blank=True)
    n_gold = models.IntegerField(default=None, null=True, blank=True)
    n_silver = models.IntegerField(default=None, null=True, blank=True)
    n_bronze = models.IntegerField(default=None, null=True, blank=True)
    n_medals = models.IntegerField(default=None, null=True, blank=True)
    n_other_medals = models.IntegerField(default=None, null=True, blank=True)
    n_first_places = models.IntegerField(default=None, null=True, blank=True)
    n_second_places = models.IntegerField(default=None, null=True, blank=True)
    n_third_places = models.IntegerField(default=None, null=True, blank=True)
    n_top_ten_places = models.IntegerField(default=None, null=True, blank=True)

    class Meta:
        indexes = [
            DescNullsLastIndex(fields=['resource', 'country']),
            DescNullsLastIndex(fields=['resource', 'rating', 'country']),
            DescNullsLastIndex(fields=['resource', '-rating', 'country']),
            DescNullsLastIndex(fields=['resource', 'resource_rank', 'country']),
            DescNullsLastIndex(fields=['resource', '-resource_rank', 'country']),
            DescNullsLastIndex(fields=['resource', 'n_accounts', 'country']),
            DescNullsLastIndex(fields=['resource', '-n_accounts', 'country']),
            DescNullsLastIndex(fields=['resource', '-n_win', '-n_gold', '-n_silver', '-n_bronze',
                                       '-n_other_medals', 'country']),
            DescNullsLastIndex(fields=['resource', '-n_first_places', '-n_second_places', '-n_third_places',
                                       '-n_top_ten_places', 'country'])
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
        delta = -1
    elif signal is post_save and kwargs['created']:
        delta = +1
    else:
        return
    update_fields = ['n_accounts']
    instance.resource.n_accounts += delta
    if instance.account_type == AccountType.UNIVERSITY:
        instance.resource.n_university_accounts += delta
        update_fields.append('n_university_accounts')
    elif instance.account_type == AccountType.TEAM:
        instance.resource.n_team_accounts += delta
        update_fields.append('n_team_accounts')
    instance.resource.save(update_fields=update_fields)


@receiver(pre_save, sender=Account)
@receiver(m2m_changed, sender=Account.coders.through)
def update_account_url(signal, instance, **kwargs):
    if kwargs.get('reverse'):
        return
    account = instance

    if signal is pre_save:
        if not account.has_field('url') or account.url:
            return
        account.url = account.account_default_url()
    elif signal is m2m_changed:
        action = kwargs.get('action')
        if not action or not action.startswith('post_'):
            return
        update_account_by_coders(account)


@receiver(m2m_changed, sender=Account.writer_set.through)
def update_account_writer(**kwargs):
    update_n_field_on_change(**kwargs, field='n_writers')


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
    account = models.ForeignKey(Account, on_delete=models.CASCADE, db_index=True)
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    place = models.CharField(max_length=17, default=None, null=True, blank=True)
    place_as_int = models.IntegerField(default=None, null=True, blank=True)
    solving = models.FloatField(default=0, blank=True)
    upsolving = models.FloatField(default=None, null=True, blank=True)
    total_solving = models.FloatField(default=0, blank=True)
    penalty = models.FloatField(default=None, null=True, blank=True)
    addition = models.JSONField(default=dict, blank=True)
    url = models.TextField(null=True, blank=True)
    new_global_rating = models.IntegerField(null=True, blank=True, default=None)
    global_rating_change = models.IntegerField(null=True, blank=True, default=None)
    skip_in_stats = models.BooleanField(default=False)
    advanced = models.BooleanField(default=False)
    last_activity = models.DateTimeField(default=None, null=True, blank=True)
    rating_prediction = models.JSONField(default=None, null=True, blank=True)
    n_solved = models.IntegerField(default=0, blank=True)
    n_upsolved = models.IntegerField(default=None, null=True, blank=True)
    n_total_solved = models.IntegerField(default=0, blank=True)
    n_first_ac = models.IntegerField(default=0, blank=True)
    medal = models.CharField(max_length=20, null=True, blank=True)
    related = models.ForeignKey('Statistics', null=True, blank=True, on_delete=models.CASCADE,
                                related_name='related_statistics')

    class StatisticsManager(BaseManager):
        def get_queryset(self):
            queryset = super().get_queryset()
            statistics_fields = [field.name for field in Statistics._meta.get_fields() if field.concrete]
            accounts_fields = [f'account__{field.name}' for field in Account._meta.get_fields() if field.concrete]
            return queryset.select_related('account', 'contest', 'resource').only(
                *statistics_fields,
                *accounts_fields,
                'contest__kind', 'contest__resource_id', 'contest__is_rated',
                'contest__title', 'contest__url', 'contest__standings_url',
                'contest__n_statistics', 'contest__start_time', 'contest__end_time',
                'resource__host', 'resource__info',
            )

    objects = BaseManager()
    saved_objects = StatisticsManager()

    class Meta:
        verbose_name_plural = 'Statistics'
        unique_together = ('account', 'contest')

        indexes = [
            models.Index(fields=['contest', 'place_as_int', '-solving', 'id']),
            models.Index(fields=['account', 'skip_in_stats']),
            models.Index(fields=['-created'], condition=Q(place_as_int__lte=3), name='statistics_created_top3'),
        ]

    @staticmethod
    def is_special_addition_field(field):
        if not field:
            return False
        if field[0] == '_' or field[-1] == '_':
            return True
        return field in settings.ADDITION_HIDE_FIELDS_

    def __str__(self):
        return f'Statistics#{self.id} Account#{self.account_id} on Contest#{self.contest_id}'

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

    def get_medal(self) -> str | None:
        return get_item(self, 'addition.medal')

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

    def update_stats(self) -> list[str]:
        problem_stats = get_statistic_stats(self.addition, solving=self.solving)
        update_fields = []
        for k, v in problem_stats.items():
            if getattr(self, k, None) != v:
                setattr(self, k, v)
                update_fields.append(k)
        if (medal := self.get_medal()) != self.medal:
            self.medal = medal
            update_fields.append('medal')
        self.save(update_fields=update_fields)
        return update_fields


def _get_statistic_stats(instance):
    return get_statistic_stats(instance.addition, solving=instance.solving,
                               with_n_medal_field=True, with_n_place_field=instance.place_as_int)


@receiver(post_init, sender=Statistics)
def statistics_post_init(sender, instance, **kwargs):
    instance._stats = _get_statistic_stats(instance)


@receiver(post_save, sender=Statistics)
@receiver(post_delete, sender=Statistics)
def update_account_from_statistic(signal, instance, **kwargs):
    if instance.resource.is_major_kind(instance.contest):
        if signal is post_delete:
            diff = {field: -value for field, value in instance._stats.items() if value}
        elif signal is post_save:
            diff = _get_statistic_stats(instance)
            if not kwargs['created']:
                for field, value in instance._stats.items():
                    diff[field] = (diff.get(field) or 0) - (value or 0)
        else:
            diff = {}
        updated_fields = []
        for field, value in diff.items():
            if not value:
                continue
            account = instance.account
            setattr(account, field, sum_with_none(getattr(account, field), value))
            updated_fields.append(field)
        if updated_fields:
            instance.account.save(update_fields=updated_fields)

    if instance.skip_in_stats or kwargs.get('update_fields'):
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

    class VirtualStartStatistic:
        def __init__(self, virtual_start):
            self.id = f'virtualstart{virtual_start.pk}'
            self.contest_id = virtual_start.object_id if virtual_start.content_type.model == 'contest' else None
            self.place = virtual_start.addition.get('place')
            self.solving = virtual_start.addition.get('solving')
            self.addition = virtual_start.addition
            self.virtual_start = True
            self.virtual_start_pk = virtual_start.pk

    @classmethod
    def filter_by_content_type(cls, model_class, prefetch=True):
        content_type = ContentType.objects.get_for_model(model_class)
        qs = cls.objects.filter(content_type=content_type)
        if prefetch:
            qs = qs.prefetch_related(Prefetch('entity', queryset=model_class.objects.all()))
        return qs

    @staticmethod
    def contests_filter(coder):
        has_virtual_start = VirtualStart.filter_by_content_type(Contest).filter(coder=coder, object_id=OuterRef('id'))
        has_verdict = coder.verdicts.filter(problem__contests=OuterRef('pk'))
        return Exists(has_virtual_start) | Exists(has_verdict)

    def is_active(self):
        return self.finish_time is None or self.finish_time > timezone.now()

    def statistics(self):
        return [self.VirtualStartStatistic(self)]


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
        contests = Contest.objects.filter(live_statistics__isnull=False, end_time__gt=timezone.now())
        return contests.order_by('end_time').first()

    def create_for_contest(self, contest):
        self.pk = None
        self.contest = contest
        self.save()

    def __str__(self):
        return f'ParseStatistics#{self.pk} contest#{self.contest_id}'


class FinalistManager(BaseManager):
    def get_queryset(self):
        return super().get_queryset().select_related('contest').prefetch_related('accounts__resource')


class Finalist(BaseModel):
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
    name = models.CharField(max_length=400, null=True, blank=True)
    accounts = models.ManyToManyField(Account, blank=True)
    info = models.JSONField(default=dict, blank=True)
    achievement_statistics = models.ManyToManyField(Statistics, blank=True)
    achievement_updated = models.DateTimeField(default=None, null=True, blank=True)
    achievement_hash = models.CharField(max_length=32, null=True, blank=True)

    objects = FinalistManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['contest', 'name'],
                name='unique_finalist_name',
                condition=Q(name__isnull=False),
            ),
        ]

    def __str__(self):
        return f'Finalist#{self.pk} contest#{self.contest_id}'


class FinalistResourceInfo(BaseModel):
    finalist = models.ForeignKey(Finalist, on_delete=models.CASCADE)
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    rating = models.IntegerField(default=None, null=True, blank=True)
    ratings = models.JSONField(default=list, blank=True)
    updated = models.DateTimeField(default=None, null=True, blank=True)

    class Meta:
        unique_together = ('finalist', 'resource')
