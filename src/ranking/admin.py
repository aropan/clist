from django.contrib import admin
from django.utils.timezone import now
from sql_util.utils import Exists

from clist.models import Contest
from pyclist.admin import BaseModelAdmin, admin_register
from ranking.management.commands.parse_statistic import Command as parse_stat
from ranking.models import (Account, AccountMatching, AccountRenaming, AccountVerification, AutoRating, CountryAccount,
                            Module, ParseStatistics, Rating, Stage, StageContest, Statistics, VerifiedAccount,
                            VirtualStart)


class HasCoders(admin.SimpleListFilter):
    title = 'has coders'
    parameter_name = 'has_coders'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Yes'),
            ('no', 'No'),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == 'yes':
            return queryset.filter(has_coder=True)
        elif value == 'no':
            return queryset.filter(has_coder=False)
        return queryset


class HasInfo(admin.SimpleListFilter):
    title = 'has info'
    parameter_name = 'has_info'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Yes'),
            ('no', 'No'),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == 'yes':
            return queryset.filter(updated__gte=now())
        elif value == 'no':
            return queryset.filter(updated__lte=now())
        return queryset


@admin_register(Account)
class AccountAdmin(BaseModelAdmin):
    list_display = ['resource', 'key', 'name', 'country', '_has_coder', 'deleted', 'updated']
    search_fields = ['=key', '=name']
    list_filter = [HasCoders, HasInfo, 'deleted', 'resource__host']

    def _has_coder(self, obj):
        return obj.has_coder
    _has_coder.boolean = True

    def get_readonly_fields(self, request, obj=None):
        return (
            ['updated', 'n_contests', 'n_writers', 'n_subscribers',
             'last_activity', 'last_submission', 'last_rating_activity',
             'rating_update_time']
            + super().get_readonly_fields(request, obj)
        )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(has_coder=Exists('coders'))


@admin_register(AccountRenaming)
class AccountRenamingAdmin(BaseModelAdmin):
    list_display = ['pk', 'resource', 'old_key', 'new_key', 'created']
    search_fields = ['old_key', 'new_key']
    list_filter = ['resource']


@admin_register(AccountVerification)
class AccountVerificationAdmin(BaseModelAdmin):
    list_display = ['coder', 'account', 'resource']
    search_fields = ['=coder__username', '=account__key']
    list_filter = ['account__resource__host']

    def resource(self, obj):
        return obj.account.resource.host


@admin_register(VerifiedAccount)
class VerifiedAccountAdmin(BaseModelAdmin):
    list_display = ['coder', 'account', 'resource']
    search_fields = ['=coder__username', '=account__key']
    list_filter = ['account__resource__host']

    def resource(self, obj):
        return obj.account.resource.host


@admin_register(Rating)
class RatingAdmin(BaseModelAdmin):
    list_display = ['contest', 'party']
    search_fields = ['contest__title', 'party__name']
    list_filter = ['party__name', 'contest__host']

    def parse_statistic(self, request, queryset):
        ids = queryset.values_list('contest', flat=True).distinct()
        contests = Contest.objects.filter(id__in=ids)
        count, total = parse_stat().parse_statistic(contests=contests, with_check=False)
        self.message_user(request, "%d of %d parsed." % (count, total))
    parse_statistic.short_description = 'Parse statistic'

    actions = [parse_statistic]


@admin_register(AutoRating)
class AutoRatingAdmin(BaseModelAdmin):
    list_display = ['party', 'deadline', 'info']
    search_fields = ['party__name']
    list_filter = ['party']


@admin_register(Statistics)
class StatisticsAdmin(BaseModelAdmin):
    list_display = ['account', 'contest', 'place', 'solving', 'upsolving', '_skip', '_adv']
    search_fields = ['=account__key']
    list_filter = ['skip_in_stats']

    def get_readonly_fields(self, *args, **kwargs):
        return ['last_activity'] + super().get_readonly_fields(*args, **kwargs)

    def _skip(self, obj):
        return obj.skip_in_stats
    _skip.boolean = True
    _skip.short_description = 'Skip'

    def _adv(self, obj):
        return obj.advanced
    _adv.boolean = True
    _adv.short_description = 'Adv'


@admin_register(Stage)
class StageAdmin(BaseModelAdmin):
    list_display = ['contest', 'filter_params']
    search_fields = ['contest__title', 'contest__resource__host', 'filter_params', 'score_params']
    list_filter = ['contest__host']
    ordering = ['-contest__start_time']

    class StageContestInline(admin.TabularInline):
        model = StageContest
        raw_id_fields = ['contest']
        ordering = ['-contest__start_time']

        def has_add_permission(self, request, obj=None):
            return False

        def has_change_permission(self, request, obj=None):
            return False

    inlines = [StageContestInline]


@admin_register(Module)
class ModuleAdmin(BaseModelAdmin):
    list_display = ['resource',
                    'enable',
                    'min_delay_after_end',
                    'max_delay_after_end',
                    'delay_on_error',
                    'delay_on_success',
                    'long_contest_idle',
                    'long_contest_divider',
                    'path']
    search_fields = ['resource__host']
    list_filter = ['enable']


@admin_register(VirtualStart)
class VirtualStartAdmin(BaseModelAdmin):
    list_display = ['id', 'coder', 'entity', 'start_time']
    date_hierarchy = 'created'
    search_fields = ['coder__username']


@admin_register(StageContest)
class StageContestAdmin(BaseModelAdmin):
    list_display = ['stage', 'contest', 'created', 'modified']
    list_filter = ['contest__resource']


@admin_register(CountryAccount)
class CountryAccountAdmin(BaseModelAdmin):
    list_display = ['resource', 'country', 'n_accounts', 'n_rating_accounts', 'rating', 'resource_rank', 'raw_rating']
    search_fields = ['country']
    list_filter = ['resource']


@admin_register(AccountMatching)
class AccountMatchingAdmin(BaseModelAdmin):
    list_display = ['name', 'status', 'coder', '_n_found_accounts', '_n_found_coders', '_n_different_coders',
                    'modified', 'statistic']
    search_fields = ['name', 'account__key', 'contest__title', 'resource__host', 'coder__username']
    list_filter = ['status']

    def _n_found_accounts(self, obj):
        return obj.n_found_accounts
    _n_found_accounts.admin_order_field = 'n_found_accounts'
    _n_found_accounts.short_description = 'NA'

    def _n_found_coders(self, obj):
        return obj.n_found_coders
    _n_found_coders.admin_order_field = 'n_found_coders'
    _n_found_coders.short_description = 'NC'

    def _n_different_coders(self, obj):
        return obj.n_different_coders
    _n_different_coders.admin_order_field = 'n_different_coders'
    _n_different_coders.short_description = 'NDC'


@admin_register(ParseStatistics)
class ParseStatisticsAdmin(BaseModelAdmin):
    list_display = ['enable', 'delay', 'contest__start_time', 'contest', 'created', 'modified']
    search_fields = ['contest__title', 'contest__host', 'contest__resource__host']
    list_filter = ['contest__resource']

    def get_readonly_fields(self, *args, **kwargs):
        return ['parse_time'] + super().get_readonly_fields(*args, **kwargs)
