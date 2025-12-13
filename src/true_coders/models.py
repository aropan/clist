import re
import uuid
from collections import Counter
from datetime import timedelta

from django.apps import apps
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField
from django.core.cache import cache
from django.db import models
from django.db.models import Case, Count, F, OuterRef, Q, Subquery, When, signals
from django.db.models.signals import post_delete, post_init, post_save
from django.dispatch import receiver
from django.utils import timezone
from django_countries.fields import CountryField
from django_super_deduper.merge import MergedModelInstance
from guardian.shortcuts import get_objects_for_user
from phonenumber_field.modelfields import PhoneNumberField
from sql_util.utils import Exists, SubquerySum

from clist.models import Contest, Problem, ProblemVerdict, Resource
from pyclist.indexes import GistIndexTrgrmOps
from pyclist.models import BaseManager, BaseModel
from utils.signals import update_foreign_key_n_field_on_change
from utils.strings import generate_secret


class Coder(BaseModel):
    user = models.OneToOneField(User, null=True, blank=True, on_delete=models.CASCADE)
    username = models.CharField(max_length=255, unique=True, blank=True)
    first_name_native = models.CharField(max_length=255, blank=True)
    last_name_native = models.CharField(max_length=255, blank=True)
    middle_name_native = models.CharField(max_length=255, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    organization = models.ForeignKey('Organization', null=True, blank=True, on_delete=models.SET_NULL)
    timezone = models.CharField(max_length=32, default="UTC")
    settings = models.JSONField(default=dict, blank=True)
    country = CountryField(null=True, blank=True)
    auto_detect_country = models.BooleanField(default=False, blank=True)
    phone_number = PhoneNumberField(blank=True)
    addition_fields = models.JSONField(default=dict, blank=True)
    n_accounts = models.IntegerField(default=0, db_index=True)
    n_contests = models.IntegerField(default=0, db_index=True)
    n_subscribers = models.IntegerField(default=0, db_index=True, blank=True)
    n_listvalues = models.IntegerField(default=0, db_index=True, blank=True)
    tshirt_size = models.CharField(max_length=10, default=None, null=True, blank=True)
    is_virtual = models.BooleanField(default=False, db_index=True)
    global_rating = models.IntegerField(null=True, blank=True, default=None, db_index=True)
    last_activity = models.DateTimeField(null=True, blank=True, default=None, db_index=True)

    class Meta:
        indexes = [
            GistIndexTrgrmOps(fields=['username']),
        ]

    def __str__(self):
        return "%s" % (self.username)

    @property
    def chat(self):
        if not hasattr(self, 'cchat'):
            self.cchat = list(self.chat_set.filter(is_group=False))
        return self.cchat[0] if self.cchat else None

    def get_contest_filter(self, categories=None, ignores=None, filters=None):
        if categories is not None:
            if not isinstance(categories, (list, tuple, set)):
                categories = (categories, )
            filter_categories = Q()
            filter_categories_with_coder = Q()
            for c in categories:
                if '@' in c:
                    c, coder = c.split('@', 1)
                    filter_categories_with_coder |= Q(coder__username=coder, categories__contains=[c])
                else:
                    filter_categories |= Q(categories__contains=[c])
            if ignores:
                filter_categories &= ~Q(id__in=ignores)

            if filter_categories_with_coder:
                filters = Filter.objects.filter(filter_categories_with_coder, enabled=True)
            elif self is not None:
                filters = self.filter_set.filter(filter_categories, enabled=True)
            else:
                filters = []
        elif filters is not None:
            pass
        else:
            raise ValueError('categories or filters must be not None')

        hide = Q()
        show = Q()
        for filter_ in filters:
            query = Q()
            if filter_.resources:
                query &= Q(resource__id__in=filter_.resources)
            if filter_.duration_from:
                seconds = timedelta(minutes=filter_.duration_from).total_seconds()
                query &= Q(duration_in_secs__gte=seconds)
            if filter_.duration_to:
                seconds = timedelta(minutes=filter_.duration_to).total_seconds()
                query &= Q(duration_in_secs__lte=seconds)
            if filter_.start_time_from:
                minutes = filter_.start_time_from * 60
                hours = minutes // 60
                minutes = minutes % 60
                query &= Q(start_time__hour__gt=hours) | Q(start_time__hour=hours, start_time__minute__gte=minutes)
            if filter_.start_time_to:
                minutes = filter_.start_time_to * 60
                hours = minutes // 60
                minutes = minutes % 60
                query &= Q(start_time__hour__lt=hours) | Q(start_time__hour=hours, start_time__minute__lte=minutes)
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
            if filter_.host:
                query &= Q(host=filter_.host)
            if filter_.week_days:
                query &= Q(start_time__week_day__in=filter_.week_days)
            if filter_.contest_id:
                query &= Q(pk=filter_.contest_id)
            if filter_.party_id:
                query &= Q(ratings__party_id=filter_.party_id)

            if filter_.to_show:
                show |= query
            else:
                hide |= query
        result = ~hide & show
        return result

    def get_categories(self):
        categories = [{'id': c, 'text': c} for c in Filter.CATEGORIES]
        for chat in self.chat_set.filter(is_group=True).order_by('pk'):
            categories.append({
                'id': chat.chat_id,
                'text': chat.get_group_name(),
            })
        return categories

    def get_notifications(self):
        ret = list(django_settings.NOTIFICATION_CONF.METHODS_CHOICES)
        for chat in self.chat_set.filter(is_group=True):
            ret.append((chat.get_notification_method(), chat.get_group_name()))
        return ret

    def account_set_order_by_pk(self):
        return self.account_set.select_related('resource').order_by('pk')

    @property
    def ordered_filter_set(self):
        return self.filter_set.order_by('created')

    @property
    def grouped_filter_set(self):
        qs = self.filter_set.select_related('contest')
        qs = qs.annotate(has_contest=Count('contest'))
        qs = qs.order_by('has_contest', 'categories', '-modified')
        return qs

    def get_account(self, host):
        return self.account_set.filter(resource__host=host).first()

    def get_ordered_resources(self):
        return Resource.objects \
            .annotate(n=SubquerySum('account__n_contests', filter=Q(coders=self))) \
            .order_by(F('n').desc(nulls_last=True), '-has_rating_history', '-n_contests')

    @property
    def display_name(self):
        return self.settings['display_name'] if self.is_virtual else self.username

    @property
    def detailed_name(self):
        if self.is_virtual:
            return self.settings['display_name']

        if self.user.first_name and self.user.last_name:
            ret = f'{self.user.first_name} {self.user.last_name}'
        elif self.user.first_name or self.user.last_name:
            ret = self.user.first_name or self.user.last_name
        elif self.first_name_native and self.last_name_native:
            ret = f'{self.first_name_native} {self.last_name_native}'
        elif self.first_name_native or self.last_name_native:
            ret = self.first_name_native or self.last_name_native
        else:
            return self.username

        return f'{self.username} aka {ret}'

    @property
    def has_global_rating(self):
        return django_settings.ENABLE_GLOBAL_RATING_ and self.global_rating is not None

    def detect_country(self):
        if self.country and not self.auto_detect_country:
            return
        countries = self.account_set.filter(country__isnull=False).values_list('country', flat=True)
        if countries:
            counter = Counter(countries)
            max_counter, max_country = max([(v, k) for k, v in counter.items()])
            if self.country != max_country and 2 * max_counter > len(countries):
                self.country = max_country
                self.auto_detect_country = True
                self.save(update_fields=['country', 'auto_detect_country'])

    def add_account(self, account):
        coder = self
        resource = account.resource

        if resource.with_single_account(account):
            virtual = account.coders.filter(is_virtual=True).first()
            if virtual:
                accounts = list(virtual.account_set.all())
                for a in accounts:
                    a.coders.add(coder)
                virtual.account_set.clear()
                NotificationMessage = apps.get_model('notification.NotificationMessage')
                NotificationMessage.link_accounts(to=coder, accounts=accounts)
                MergedModelInstance(primary_object=coder, keep_old=False, merge_field_values=False).merge(virtual)
            account.coders.clear()

        account.coders.add(coder)
        account.updated = timezone.now()
        account.save()
        coder.detect_country()

    def primary_account(self, resource=None, accounts=None):
        if resource is not None:
            qs = self.account_set.filter(resource=resource)
        elif accounts is not None:
            qs = accounts.filter(coders=self)
        else:
            raise ValueError('resource or accounts must be not None')
        qs = qs.annotate(has_rating=Case(When(rating__isnull=False, then=True), default=False))
        return qs.order_by('account_type', '-has_rating', '-n_contests').first()

    def primary_accounts(self, accounts=None):
        if accounts is not None:
            qs = accounts.filter(coders=self)
        else:
            qs = self.account_set.all()
        qs = qs.annotate(has_rating=Case(When(rating__isnull=False, then=True), default=False))
        qs = qs.order_by('resource', 'account_type', '-has_rating', '-n_contests')
        qs = qs.distinct('resource')
        return qs

    def get_limit(self, name, default=None):
        return self.settings.get('limits', {}).get(name, default)

    def set_limit(self, name, value):
        limits = self.settings.setdefault('limits', {})
        ret = limits.get(name) != value
        limits[name] = value
        return ret

    @property
    def n_subscriptions_limit(self):
        return self.get_limit('n_subscriptions', django_settings.CODER_N_SUBSCRIPTIONS_LIMIT_)

    @property
    def subscription_top_n_limit(self):
        return self.get_limit('subscription_top_n', django_settings.CODER_SUBSCRIPTION_TOP_N_LIMIT_)

    @property
    def subscription_n_limit(self):
        return self.get_limit('subscription_n', django_settings.CODER_SUBSCRIPTION_N_LIMIT_)

    def update_or_get_setting(self, field, value):
        if value is not None:
            self.settings[field] = value
            self.save(update_fields=['settings'])
        else:
            value = self.settings.get(field)
        return value

    @staticmethod
    def apply_coder_kind(queryset, coder_kind, logger=None):
        if not coder_kind or coder_kind == 'all':
            return queryset
        if coder_kind == 'real':
            return queryset.filter(is_virtual=False)
        elif coder_kind == 'ghost' or coder_kind == 'virtual':
            return queryset.filter(is_virtual=True)
        elif coder_kind == 'none':
            return queryset.none()
        else:
            if logger:
                logger.warning(f'Unknown coder kind: {coder_kind}')
            return queryset


class CoderProblem(BaseModel):
    coder = models.ForeignKey(Coder, on_delete=models.CASCADE, related_name='verdicts')
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name='verdicts')
    contest = models.ForeignKey(Contest, null=True, blank=True, on_delete=models.CASCADE)
    statistic = models.ForeignKey('ranking.Statistics', null=True, blank=True, on_delete=models.CASCADE)
    problem_key = models.CharField(max_length=255, null=True, blank=True)
    verdict = models.CharField(max_length=2, choices=ProblemVerdict.choices, db_index=True)
    upsolving = models.BooleanField(null=True, blank=True, db_index=True)
    submission_time = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        unique_together = ('coder', 'problem')

        indexes = [
            models.Index(fields=['coder', 'verdict']),
            models.Index(fields=['problem', 'verdict']),
            models.Index(fields=['coder', 'submission_time']),
        ]


@receiver(signals.pre_save, sender=Coder)
def init_coder_username(instance, **kwargs):
    if not instance.username:
        instance.username = instance.user.username
    if 'api_throttle_at' in instance.settings:
        limit_key = str(instance.username) + '[limit]'
        cache.delete(limit_key)


@receiver(signals.pre_delete, sender=Coder)
def clear_coder_accounts(instance, **kwargs):
    accounts = instance.account_set.select_related('resource').prefetch_related('coders')
    for a in accounts:
        a.coders.remove(instance)


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
    admins = models.ManyToManyField(Coder, blank=True, related_name='party_admin_set')
    is_hidden = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.secret_key:
            self.secret_key = generate_secret(length=20)
        return super(Party, self).save(*args, **kwargs)

    def __str__(self):
        return self.name

    def has_permission_toggle_contests(self, coder):
        return bool(coder and (self.author == coder or self.admins.filter(pk=coder.pk).exists()))

    class Meta:
        verbose_name_plural = 'Parties'

    objects = PartyManager()


def _get_default_categories():
    return Filter.CATEGORIES


def _get_default_week_days():
    return []


class Filter(BaseModel):
    CATEGORIES = ['list', 'calendar', 'email', 'telegram', 'api', 'webbrowser']

    coder = models.ForeignKey(Coder, on_delete=models.CASCADE, db_index=True)
    enabled = models.BooleanField(default=True)
    name = models.CharField(max_length=60, null=True, blank=True)
    duration_from = models.IntegerField(null=True, blank=True)
    duration_to = models.IntegerField(null=True, blank=True)
    start_time_from = models.FloatField(null=True, blank=True)
    start_time_to = models.FloatField(null=True, blank=True)
    regex = models.CharField(max_length=1000, null=True, blank=True)
    inverse_regex = models.BooleanField(default=False)
    to_show = models.BooleanField(default=True)
    resources = models.JSONField(default=list, blank=True)
    host = models.TextField(default=None, null=True, blank=True)
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE, default=None, null=True, blank=True, db_index=True)
    party = models.ForeignKey(Party, on_delete=models.CASCADE, default=None, null=True, blank=True, db_index=True)
    categories = ArrayField(models.CharField(max_length=20), blank=True, default=_get_default_categories)
    week_days = ArrayField(models.PositiveSmallIntegerField(), blank=True, default=_get_default_week_days)

    def __str__(self):
        result = '' if not self.name else '{0.name}: '.format(self)
        result += '{0.coder}, {0.resources} resources, {0.contest} contest'.format(self)
        if self.duration_from is not None or self.duration_to is not None:
            result += ', duration'
            if self.duration_from is not None:
                result += ' from {0.duration_from}'.format(self)
            if self.duration_to is not None:
                result += ' to {0.duration_to}'.format(self)
        if self.start_time_from is not None or self.start_time_to is not None:
            result += ', start time'
            if self.start_time_from is not None:
                result += ' from {0.start_time_from}'.format(self)
            if self.start_time_to is not None:
                result += ' to {0.start_time_to}'.format(self)
        if self.regex is not None:
            result += ', regex '
            if self.inverse_regex:
                result += '!'
            result += '= ' + self.regex
        if self.host is not None:
            result += ', host = {}'.format(self.host)
        return result

    def dict(self):
        ret = {
            "name": self.name,
            "id": self.id,
            "duration": {
                "from": self.duration_from or "",
                "to": self.duration_to or "",
            },
            "start_time": {
                "from": self.start_time_from or "",
                "to": self.start_time_to or "",
            },
            "regex": self.regex or "",
            "host": self.host or "",
            "resources": self.resources,
            "contest": self.contest_id,
            "party": self.party_id,
            "categories": self.categories,
            "week_days": self.week_days,
            "inverse_regex": self.inverse_regex,
            "to_show": self.to_show,
            "enabled": self.enabled,
        }
        if self.contest_id:
            ret['contest__title'] = self.contest.title
        if self.party_id:
            ret['party__name'] = self.party.name
        return ret

    class Meta:
        indexes = [
            models.Index(fields=['coder']),
            models.Index(fields=['contest']),
            models.Index(fields=['coder', 'contest']),
        ]


class AccessLevel(models.TextChoices):
    PRIVATE = 'private', 'Private'
    RESTRICTED = 'restricted', 'Restricted'
    PUBLIC = 'public', 'Public'


class CoderList(BaseModel):
    name = models.CharField(max_length=60)
    owner = models.ForeignKey(Coder, related_name='my_list_set', on_delete=models.CASCADE, db_index=True)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True, editable=False)
    access_level = models.CharField(max_length=10, choices=AccessLevel.choices, default=AccessLevel.PRIVATE)
    shared_with_coders = models.ManyToManyField(Coder, related_name='shared_list_set', blank=True)
    custom_names = models.BooleanField(default=False)
    account_update_delay = models.DurationField(null=True, blank=True)
    locale = models.CharField(max_length=5, choices=django_settings.LOCALE_CHOICES, null=True, blank=True)

    class Meta:
        permissions = (
            ('manage_coderlist', 'Can manage coder lists'),
        )

    def __str__(self):
        return f'{self.name} CoderList#{self.id}'

    def shared_with_select_data(self):
        return [{'id': c.pk, 'username': c.username} for c in self.shared_with_coders.all()]

    @staticmethod
    def filter_for_coder(coder):
        qs = CoderList.objects
        condition = Q(access_level=AccessLevel.PUBLIC)
        if coder:
            qs = qs.annotate(has_shared_with=Exists('shared_with_coders', filter=Q(coder=coder)))
            condition |= Q(owner=coder) | Q(access_level=AccessLevel.RESTRICTED, has_shared_with=True)
        return qs.filter(condition)

    @staticmethod
    def filter_for_manager(coder):
        managed_coderlist = get_objects_for_user(coder.user, 'true_coders.manage_coderlist', with_superuser=False)
        return CoderList.objects.filter(Q(owner=coder) | Q(pk__in=managed_coderlist))

    @staticmethod
    def filter_for_coder_and_uuids(coder, uuids, logger=None):
        qs = CoderList.filter_for_coder(coder=coder)
        active_filter = Q(owner=coder) | Q(uuid__in=uuids)
        if coder:
            managed = get_objects_for_user(
                coder.user,
                'true_coders.manage_coderlist',
                CoderList,
                accept_global_perms=False,
                with_superuser=False,
            )
            active_filter |= Q(pk__in=managed)
        qs = qs.filter(active_filter)
        used_uuids = set(map(str, qs.values_list('uuid', flat=True)))
        filtered_uuids = []
        for uuid in uuids:
            if uuid in used_uuids:
                filtered_uuids.append(uuid)
            elif logger:
                logger.warning(f'Ignore list with uuid = "{uuid}"')
        return qs, filtered_uuids

    @staticmethod
    def coders_and_accounts_ids(uuids, coder=None, logger=None):
        coders = set()
        accounts = set()
        for uuid in uuids:
            try:
                coder_list = CoderList.filter_for_coder(coder).prefetch_related('values').get(uuid=uuid)
            except Exception:
                if logger:
                    logger.warning(f'Ignore list with uuid = "{uuid}"')
                continue
            for v in coder_list.related_values:
                if v.coder:
                    coders.add(v.coder.pk)
                if v.account:
                    accounts.add(v.account.pk)
        return coders, accounts

    @staticmethod
    def accounts_annotate(uuids):
        groups = ListGroup.objects.filter(coder_list__uuid__in=uuids, coder_list__custom_names=True, name__isnull=False)
        groups = groups.filter(Q(values__account=OuterRef('pk')) | Q(values__coder__account=OuterRef('pk')))
        annotation = Subquery(groups.values('name')[:1])
        return annotation

    @staticmethod
    def accounts_filter(uuids, coder=None, logger=None):
        coders, accounts = CoderList.coders_and_accounts_ids(uuids, coder=coder, logger=logger)
        ret = Q()
        if coders:
            Account = apps.get_model('ranking', 'Account')
            accounts |= set(Account.objects.filter(coders__pk__in=coders).values_list('pk', flat=True))
        if accounts:
            ret |= Q(pk__in=accounts)
        if not ret and uuids:
            ret = Q(id=0)
        return ret

    @staticmethod
    def coders_filter(uuids, coder=None, logger=None):
        coders, accounts = CoderList.coders_and_accounts_ids(uuids, coder=coder, logger=logger)
        ret = Q()
        if accounts:
            Coder = apps.get_model('true_coders', 'Coder')
            coders |= set(Coder.objects.filter(account__pk__in=accounts).values_list('pk', flat=True))
        if coders:
            ret |= Q(pk__in=coders)
        if not ret and uuids:
            ret = Q(id=0)
        return ret

    @property
    def related_groups(self):
        return self.groups.prefetch_related('values__coder__user', 'values__account__resource').order_by('pk')

    @property
    def related_values(self):
        return self.values.select_related('coder__user', 'account__resource')

    def update_coders_or_accounts(self):
        coders, accounts = CoderList.coders_and_accounts_ids([self.uuid], coder=self.owner)
        for subscription in self.subscription_set.all():
            subscription.coders.set(coders)
            subscription.accounts.set(accounts)

    def can_manage(self, coder, user=None):
        return coder and (coder == self.owner or (user or coder.user).has_perm('true_coders.manage_coderlist', self))


class ListGroup(BaseModel):
    name = models.CharField(max_length=200, null=True, blank=True)
    coder_list = models.ForeignKey(CoderList, related_name='groups', on_delete=models.CASCADE)

    def __str__(self):
        return f'{self.name} ListGroup#{self.id}'

    def profile_str(self):
        ret = []
        for value in self.values.all():
            if value.coder:
                ret.append(value.coder.username)
            elif value.account:
                prefix = value.account.resource.short_host or value.account.resource.host
                ret.append(f'{prefix}:{value.account.key}')
        return ','.join(ret)


class ListValue(BaseModel):
    coder = models.ForeignKey(Coder, null=True, blank=True, on_delete=models.CASCADE)
    account = models.ForeignKey('ranking.Account', null=True, blank=True, on_delete=models.CASCADE)
    coder_list = models.ForeignKey(CoderList, related_name='values', on_delete=models.CASCADE)
    group = models.ForeignKey(ListGroup, related_name='values', on_delete=models.CASCADE)

    def __str__(self):
        if self.coder:
            return f'Coder#{self.coder_id} ListValue#{self.id}'
        if self.account:
            return f'Account#{self.account_id} ListValue#{self.id}'
        return f'{self.name} ListValue#{self.id}'

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['coder_list', 'coder'],
                condition=Q(coder__isnull=False),
                name='unique_coder',
            ),
            models.UniqueConstraint(
                fields=['coder_list', 'account', 'group'],
                condition=Q(account__isnull=False),
                name='unique_account',
            ),
        ]

        indexes = [
            models.Index(fields=['coder_list', 'group']),
        ]


@receiver([post_save, post_delete], sender=ListValue)
def update_list(instance, **kwargs):
    instance.coder_list.update_coders_or_accounts()


@receiver([post_init, post_save, post_delete], sender=ListValue)
def update_n_listvalues_field(**kwargs):
    update_foreign_key_n_field_on_change(**kwargs, attr='account', field='n_listvalues')
    update_foreign_key_n_field_on_change(**kwargs, attr='coder', field='n_listvalues')


class ListProblem(BaseModel):
    problem = models.ForeignKey(Problem, related_name='lists', on_delete=models.CASCADE)
    coder_list = models.ForeignKey(CoderList, related_name='problems', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('coder_list', 'problem')


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
