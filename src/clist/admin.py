from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.utils import timezone
from sql_util.utils import SubqueryCount

from clist.models import Banner, Contest, ContestSeries, Problem, ProblemTag, PromoLink, Promotion, Resource
from pyclist.admin import BaseModelAdmin, admin_register
from ranking.management.commands.parse_statistic import Command as parse_stat
from ranking.models import Module, Rating


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

    def parse_statistic(self, request, queryset):
        count, total = parse_stat().parse_statistic(queryset, with_check=False)
        self.message_user(request, "%d of %d parsed." % (count, total))
    parse_statistic.short_description = 'Parse statistic'

    fieldsets = [
        [None, {'fields': ['title', 'slug', 'title_path', 'kind', 'resource', 'host', 'url', 'standings_url',
                           'standings_kind', 'registration_url', 'trial_standings_url']}],
        ['Date information', {'fields': ['start_time', 'end_time', 'duration_in_secs']}],
        ['Secury information', {'fields': ['key']}],
        ['Addition information', {'fields': ['was_auto_added', 'auto_updated', 'n_statistics', 'has_hidden_results',
                                             'writers', 'calculate_time', 'info', 'variables', 'invisible',
                                             'is_rated', 'is_promoted', 'with_medals',
                                             'related', 'merging_contests', 'series',
                                             'allow_updating_statistics_for_participants',
                                             'set_matched_coders_to_members']}],
        ['Timing', {'fields': ['statistics_update_required', 'parsed_time', 'parsed_percentage',
                               'wait_for_successful_update_timing', 'statistic_timing', 'notification_timing',
                               'rating_prediction_timing', 'created', 'modified', 'updated']}],
        ['Rating', {'fields': ['rating_prediction_hash', 'has_fixed_rating_prediction_field',
                               'rating_prediction_fields']}],
        ['Problem', {'fields': ['n_problems', 'problem_rating_hash', 'problem_rating_update_required']}],
        ['Submission', {'fields': ['has_submissions', 'has_submissions_tests']}],
    ]
    list_display = ['title', 'host', 'start_time', 'url', 'is_rated', 'invisible', 'key', 'standings_url',
                    'created', 'modified', 'updated', 'parsed_time', 'auto_updated']
    search_fields = ['title', 'standings_url']
    list_filter = [ComingContestListFilter, PastContestListFilter, 'invisible', 'is_rated', 'resource__host']

    actions = [parse_statistic]

    def get_readonly_fields(self, request, obj=None):
        ret = ['auto_updated', 'updated', 'parsed_time', 'parsed_percentage', 'wait_for_successful_update_timing',
               'statistic_timing', 'notification_timing', 'rating_prediction_timing',
               'slug', 'title_path']
        ret += list(super().get_readonly_fields(request, obj))
        return ret

    inlines = [RatingSet]


@admin_register(ContestSeries)
class ContestSeriesAdmin(BaseModelAdmin):
    list_display = ['name', 'n_contests', 'short', 'slug', 'aliases']
    search_fields = ['name', 'short', 'slug', 'aliases']

    def n_contests(self, obj):
        return obj.n_contests

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(n_contests=SubqueryCount('contest'))
        return queryset

    class ContestInline(admin.TabularInline):
        model = Contest
        fields = ['standings_url', 'end_time']
        readonly_fields = ['standings_url', 'end_time']
        ordering = ['-end_time']
        can_delete = False
        extra = 0

    inlines = [ContestInline]


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
        [None, {'fields': ['host', 'short_host', 'enable', 'url', 'profile_url', 'avatar_url', 'problem_url', 'icon',
                           'n_accounts', 'n_contests']}],
        ['Parse information', {'fields': ['regexp', 'path', 'parse_url', 'timezone', 'auto_remove_started',
                                          'has_inherit_medals_to_related']}],
        ['Calendar information', {'fields': ['color', 'uid']}],
        ['Rating information', {'fields': ['has_rating_history', 'has_country_rating',
                                           'avg_rating', 'n_rating_accounts',
                                           'rating_update_time', 'rank_update_time',
                                           'contest_update_time', 'country_rank_update_time',
                                           'ratings', 'rating_prediction']}],
        ['Account information', {'fields': ['has_accounts_infos_update', 'n_accounts_to_update', 'has_multi_account',
                                            'has_account_verification', 'has_standings_renamed_account',
                                            'skip_for_contests_chart', 'accounts_fields']}],
        ['Problem information', {'fields': ['has_problem_rating', 'has_problem_update', 'has_problem_archive',
                                            'problem_archive_update_time', 'has_upsolving', 'problems_fields',
                                            'problem_rating_predictor']}],
        ['Statistics information', {'fields': ['statistics_fields']}],
        ['Other information', {'fields': ['info']}],
    ]
    list_display = ['host', 'short_host', 'enable', 'n_contests', 'n_accounts', 'modified',
                    '_has_rating', '_has_profile_url', '_has_problem_rating', '_has_accounts_infos_update',
                    '_has_multi_account', '_has_standings_renamed_account', '_has_upsolving', '_has_verification']
    search_fields = ['host', 'url']
    list_filter = ['has_rating_history', 'has_country_rating', HasProfileListFilter, 'enable', 'timezone',
                   'has_problem_rating', 'has_accounts_infos_update', 'has_multi_account', 'has_upsolving',
                   'has_account_verification']

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

    def _has_standings_renamed_account(self, obj):
        return obj.has_standings_renamed_account
    _has_standings_renamed_account.boolean = True
    _has_standings_renamed_account.short_description = 'ARenamed'

    def _has_upsolving(self, obj):
        return obj.has_upsolving
    _has_upsolving.boolean = True
    _has_upsolving.short_description = 'Upsolv'

    def _has_verification(self, obj):
        return obj.has_account_verification
    _has_verification.boolean = True
    _has_verification.short_description = 'AVerif'

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

    class ModuleInline(admin.StackedInline):
        model = Module
        extra = 0

    inlines = (ModuleInline, )


@admin_register(Problem)
class ProblemAdmin(BaseModelAdmin):
    list_display = ['name', 'index', 'key', 'short', 'n_attempts', 'n_accepted', 'divisions', 'url', 'visible']
    list_filter = ['visible', 'resource']
    search_fields = ['contest', 'name']


@admin_register(ProblemTag)
class ProblemTagAdmin(BaseModelAdmin):
    list_display = ['name']
    search_fields = ['name']


@admin_register(Banner)
class BannerAdmin(BaseModelAdmin):
    list_display = ['name', 'url', 'end_time', 'template']
    list_filter = ['template']
    search_fields = ['name', 'url', 'data']


@admin_register(Promotion)
class PromotionAdmin(BaseModelAdmin):
    list_display = ['contest', 'timer_message', 'time_attribute', 'background']


@admin_register(PromoLink)
class PromoLinkAdmin(BaseModelAdmin):
    list_display = ['name', 'enable', 'desc', 'url']
    search_fields = ['name']
