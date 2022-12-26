from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.db import transaction
from django.utils import timezone

from clist.models import Banner, Contest, Problem, ProblemTag, Resource, TimingContest
from pyclist.admin import BaseModelAdmin, admin_register
from ranking.management.commands.parse_statistic import Command as parse_stat
from ranking.models import Rating


@admin_register(Contest)
class ContestAdmin(BaseModelAdmin):

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

    class RatingSet(admin.TabularInline):
        model = Rating
        extra = 0

    class Timing(admin.TabularInline):
        model = TimingContest
        fields = ['statistic']
        readonly_fields = ['modified']
        extra = 0

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

    fieldsets = [
        [None, {'fields': ['title', 'slug', 'title_path', 'kind', 'resource', 'host', 'url', 'standings_url',
                           'registration_url']}],
        ['Date information', {'fields': ['start_time', 'end_time', 'duration_in_secs']}],
        ['Secury information', {'fields': ['key']}],
        ['Addition information', {'fields': ['n_statistics', 'parsed_time', 'has_hidden_results', 'calculate_time',
                                             'info', 'invisible', 'is_rated', 'with_medals', 'related']}],
        ['Access time', {'fields': ['created', 'modified', 'updated']}],
    ]
    list_display = ['title', 'host', 'start_time', 'url', 'is_rated', 'invisible', 'key', 'standings_url',
                    'created', 'modified', 'updated', 'parsed_time']
    search_fields = ['title', 'standings_url']
    list_filter = [ComingContestListFilter, PastContestListFilter, 'invisible', 'is_rated', 'resource__host']

    actions = [create_timing, parse_statistic]

    def get_readonly_fields(self, request, obj=None):
        return ['updated', ] + list(super().get_readonly_fields(request, obj))

    inlines = [RatingSet, Timing]


@admin_register(Resource)
class ResourceAdmin(BaseModelAdmin):
    class HasProfileListFilter(SimpleListFilter):
        title = 'has profile url'
        parameter_name = 'has_profile_url'

        def lookups(self, request, model_admin):
            return (
                ('0', 'No'),
                ('1', 'Yes'),
            )

        def queryset(self, request, queryset):
            if self.value() == '0':
                return queryset.filter(profile_url__isnull=True)
            elif self.value() == '1':
                return queryset.filter(profile_url__isnull=False)

    fieldsets = [
        [None, {'fields': ['host', 'short_host', 'enable', 'url', 'profile_url', 'avatar_url', 'icon',
                           'n_accounts', 'n_contests']}],
        ['Parse information', {'fields': ['regexp', 'path', 'parse_url', 'timezone']}],
        ['Calendar information', {'fields': ['color', 'uid']}],
        [None, {'fields': ['info', 'ratings',
                           'has_rating_history', 'has_problem_rating', 'has_multi_account', 'has_accounts_infos_update',
                           'avg_rating', 'accounts_fields']}],
    ]
    list_display = ['host', 'short_host', 'enable', '_has_rating', '_has_profile_url', '_has_problem_rating',
                    '_has_accounts_infos_update', '_has_multi_account', 'n_contests', 'n_accounts', 'modified']
    search_fields = ['host', 'url']
    list_filter = ['has_rating_history', HasProfileListFilter, 'enable', 'timezone', 'has_problem_rating',
                   'has_accounts_infos_update', 'has_multi_account']

    def _has_profile_url(self, obj):
        return bool(obj.profile_url)
    _has_profile_url.boolean = True
    _has_profile_url.short_description = 'PUrl'

    def _has_rating(self, obj):
        return bool(obj.ratings)
    _has_rating.boolean = True
    _has_rating.short_description = 'Rating'

    def _has_problem_rating(self, obj):
        return obj.has_problem_rating
    _has_problem_rating.boolean = True
    _has_problem_rating.short_description = 'PRating'

    def _has_accounts_infos_update(self, obj):
        return obj.has_accounts_infos_update
    _has_accounts_infos_update.boolean = True
    _has_accounts_infos_update.short_description = 'AUpdate'

    def _has_multi_account(self, obj):
        return obj.has_multi_account
    _has_multi_account.boolean = True
    _has_multi_account.short_description = 'AMulti'

    def get_list_display(self, request):
        ret = super().get_list_display(request)
        if request.GET.get('has_profile_url') == '1':
            ret = list(ret)
            try:
                ret[ret.index('_has_profile_url')] = 'profile_url'
            except ValueError:
                pass
        return ret

    def get_readonly_fields(self, request, obj=None):
        return ['n_accounts', 'n_contests'] + list(super().get_readonly_fields(request, obj))


@admin_register(Problem)
class ProblemAdmin(BaseModelAdmin):
    list_display = ['contest', 'index', 'key', 'short', 'name', 'n_tries', 'n_accepted', 'divisions', 'url', 'visible']
    list_filter = ['visible', 'resource']
    search_fields = ['contest', 'name']


@admin_register(ProblemTag)
class ProblemTagAdmin(BaseModelAdmin):
    list_display = ['name']
    search_fields = ['name']


@admin_register(TimingContest)
class TimingContestAdmin(BaseModelAdmin):
    list_display = ['contest', 'notification', 'statistic', 'modified']
    list_filter = ['contest__host']
    search_fields = ['contest__title', 'contest__host']

    def get_readonly_fields(self, request, obj=None):
        return ['notification', 'statistic', ] + \
            list(super().get_readonly_fields(request, obj))


@admin_register(Banner)
class BannerAdmin(BaseModelAdmin):
    list_display = ['name', 'url', 'end_time', 'template']
    list_filter = ['template']
    search_fields = ['name', 'url', 'data']
