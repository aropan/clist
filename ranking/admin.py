from django.contrib import admin
from django.utils.timezone import now
from sql_util.utils import Exists

from clist.models import Contest
from pyclist.admin import BaseModelAdmin, admin_register
from ranking.management.commands.parse_statistic import Command as parse_stat
from ranking.models import Account, AutoRating, Module, Rating, Stage, Statistics


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
    list_display = ['resource', 'key', 'name', 'country', '_has_coder', 'updated']
    search_fields = ['=key', '=name']
    list_filter = [HasCoders, HasInfo, 'resource__host']

    def _has_coder(self, obj):
        return obj.has_coder
    _has_coder.boolean = True

    def get_readonly_fields(self, request, obj=None):
        return ['updated', 'n_contests', 'n_writers', 'last_activity'] + super().get_readonly_fields(request, obj)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(has_coder=Exists('coders'))

    class StatisticsSet(admin.TabularInline):
        model = Statistics
        ordering = ('-contest__end_time', )
        raw_id_fields = ('contest', )
        fields = ('contest', )
        readonly_fields = ('contest', )
        can_delete = False
        extra = 0

        def get_queryset(self, *args, **kwargs):
            qs = super().get_queryset(*args, **kwargs)
            return qs.select_related('contest')

    inlines = [StatisticsSet]


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
    list_display = ['account', 'contest', 'place', 'solving', 'upsolving']
    search_fields = ['=account__key']
    list_filter = ['contest__host']


@admin_register(Stage)
class StageAdmin(BaseModelAdmin):
    list_display = ['contest', 'filter_params', 'score_params']
    search_fields = ['contest__title', 'contest__resource__host']
    list_filter = ['contest__host']

    def parse_stage(self, request, queryset):
        for stage in queryset:
            stage.update()
    parse_stage.short_description = 'Parse stages'

    actions = [parse_stage]


@admin_register(Module)
class ModuleAdmin(BaseModelAdmin):
    list_display = ['resource',
                    'multi',
                    'min_delay_after_end',
                    'max_delay_after_end',
                    'delay_on_error',
                    'delay_on_success',
                    'path']
    list_filter = ['has_accounts_infos_update']
    search_fields = ['resource__host']

    def multi(self, obj):
        return obj.multi_account_allowed
    multi.boolean = True
