from pyclist.admin import BaseModelAdmin, admin_register
from django.contrib import admin
from clist.models import Resource, Contest, TimingContest, Banner
from ranking.models import Rating
from django.db import transaction
from ranking.management.commands.parse_statistic import Command as parse_stat
from django.contrib.admin import SimpleListFilter
from django.utils import timezone


class PastContestListFilter(SimpleListFilter):
    title = 'past'
    parameter_name = 'past'

    def lookups(self, request, model_admin):
        return (
            ('0', 'No'),
            ('1', 'Yes'),
        )

    def queryset(self, request, queryset):
        if self.value() == '0':
            return queryset.filter(end_time__gt=timezone.now())
        elif self.value() == '1':
            return queryset.filter(end_time__lte=timezone.now())


class ComingContestListFilter(SimpleListFilter):
    title = 'coming'
    parameter_name = 'coming'

    def lookups(self, request, model_admin):
        return (
            ('0', 'No'),
            ('1', 'Yes'),
        )

    def queryset(self, request, queryset):
        if self.value() == '0':
            return queryset.filter(start_time__lte=timezone.now())
        elif self.value() == '1':
            return queryset.filter(start_time__gt=timezone.now())


@admin_register(Contest)
class ContestAdmin(BaseModelAdmin):
    fieldsets = [
        [None, {'fields': ['title', 'resource', 'host', 'url', 'standings_url', 'invisible']}],
        ['Date information', {'fields': ['start_time', 'end_time', 'duration_in_secs']}],
        ['Secury information', {'fields': ['key']}],
        ['Access time', {'fields': ['created', 'modified']}],
    ]
    list_display = ['title', 'host', 'start_time', 'url', 'invisible', 'key']
    search_fields = ['title', 'standings_url']
    list_filter = [ComingContestListFilter, PastContestListFilter, 'invisible', 'resource__host']
    date_hierarchy = 'start_time'

    @transaction.atomic
    def create_timing(self, request, queryset):
        total, count = 0, 0
        for c in queryset:
            _, created = TimingContest.objects.get_or_create(contest=c)
            if created:
                count += 1
            total += 1
        self.message_user(request, "%d of %d created." % (count, total))
    create_timing.short_description = 'Create timing'

    def parse_statistic(self, request, queryset):
        count, total = parse_stat().parse_statistic(queryset, with_check=False)
        self.message_user(request, "%d of %d parsed." % (count, total))
    parse_statistic.short_description = 'Parse statistic'

    actions = [create_timing, parse_statistic]

    class RatingSet(admin.TabularInline):
        model = Rating
        extra = 0
    inlines = [RatingSet]


@admin_register(Resource)
class ResourceAdmin(BaseModelAdmin):
    fieldsets = [
        [None, {'fields': ['host', 'enable', 'url']}],
        ['Parse information', {'fields': ['regexp', 'path', 'parse_url', 'timezone']}],
        ['Calendar information', {'fields': ['color', 'uid']}],
    ]
    list_display = ['host', 'enable', 'url', 'timezone']
    list_filter = ['timezone']
    search_fields = ['host']


@admin_register(TimingContest)
class TimingContestAdmin(BaseModelAdmin):
    list_display = ['contest', 'notification', 'statistic', 'modified']
    list_filter = ['contest__host']
    search_fields = ['contest__title', 'contest__host']

    def get_readonly_fields(self, request, obj=None):
        return ['notification', 'statistic', ] + \
            list(super(TimingContestAdmin, self).get_readonly_fields(request, obj))


@admin_register(Banner)
class BannerAdmin(BaseModelAdmin):
    list_display = ['name', 'url', 'end_time', 'template']
    list_filter = ['template']
    search_fields = ['name', 'url', 'data']
