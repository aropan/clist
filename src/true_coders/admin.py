from django.contrib import admin

from events.models import Participant
from pyclist.admin import BaseModelAdmin, admin_register
from true_coders.models import Coder, CoderList, CoderProblem, Filter, ListGroup, ListValue, ListProblem, Organization, Party


@admin_register(Coder)
class CoderAdmin(BaseModelAdmin):
    search_fields = ['username', 'settings']
    list_display = ['username', 'global_rating', 'last_activity', 'settings']
    list_filter = ['party', 'account__resource']

    def get_readonly_fields(self, request, obj=None):
        return (
            ['n_accounts', 'n_contests', 'n_subscribers', 'n_listvalues', 'last_activity']
            + super().get_readonly_fields(request, obj)
        )

    def clean_settings(self, request, queryset):
        count = 0
        for c in queryset:
            if 'hide_in_calendar' in c.settings:
                c.settings.pop('hide_in_calendar')
                c.save()
                count += 1
        self.message_user(request, "%d cleaned." % count)
    clean_settings.short_description = 'Clean selected settings'
    actions = [clean_settings]

    class PartySet(admin.TabularInline):
        model = Party.coders.through
        extra = 0

    inlines = [PartySet]


@admin_register(CoderProblem)
class CoderProblemAdmin(BaseModelAdmin):
    list_display = ['coder', 'problem', 'verdict', 'created', 'modified']
    list_filter = ['verdict', 'problem__resource']
    search_fields = ['coder__username', 'problem__name']


@admin_register(Party)
class PartyAdmin(BaseModelAdmin):
    list_display = ['name', 'slug', 'contests_count', 'coders_count']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name', )}

    def contests_count(self, inst):
        return inst.rating_set.count()
    contests_count.admin_order_field = 'contests_count'

    def coders_count(self, inst):
        return inst.coders.count()
    coders_count.admin_order_field = 'coders_count'


@admin_register(Filter)
class FilterAdmin(BaseModelAdmin):
    search_fields = ['coder__user__username', 'name']
    list_display = [
        'coder',
        'enabled',
        'name',
        'to_show',
        'regex',
        'inverse_regex',
        '_n_resources',
        'contest_id',
        'categories',
        'created',
        'modified',
    ]
    list_filter = ['enabled']

    def _n_resources(self, obj):
        return len(obj.resources)


@admin_register(Organization)
class OrganizationAdmin(BaseModelAdmin):
    list_display = ['name', 'abbreviation', 'name_ru', 'participants_count', 'author']
    search_fields = ['name', 'abbreviation', 'name_ru']

    def participants_count(self, inst):
        return inst.participant_set.count()
    participants_count.admin_order_field = 'participants_count'

    class ParticipantInline(admin.StackedInline):
        model = Participant
        fields = ['is_coach']
        show_change_link = True
        can_delete = False
        extra = 0
    inlines = [ParticipantInline]


@admin_register(CoderList)
class CoderListAdmin(BaseModelAdmin):
    list_display = ['name', 'owner', 'access_level', 'locale', 'uuid']
    list_filter = ['access_level', 'locale']
    search_fields = ['name', 'owner__username', 'uuid']

    def get_readonly_fields(self, request, obj=None):
        return ['uuid'] + super().get_readonly_fields(request, obj)

    class ListGroupInline(admin.TabularInline):
        model = ListGroup
        fields = ['id', 'name', 'created', 'modified']
        readonly_fields = ['name', 'created', 'modified']
        show_change_link = True
        can_delete = False
        extra = 0

    class ListProblemInline(admin.TabularInline):
        model = ListProblem
        fields = ['id', 'problem']
        readonly_fields = ['problem', 'created', 'modified']
        show_change_link = True
        can_delete = False
        extra = 0

    inlines = [ListGroupInline, ListProblemInline]


@admin_register(ListGroup)
class ListGroupAdmin(BaseModelAdmin):
    list_display = ['id', 'coder_list']
    search_fields = ['coder_list__name', 'coder_list__uuid']

    class ListValueInline(admin.TabularInline):
        model = ListValue
        fields = ['coder', 'account', 'created', 'modified']
        readonly_fields = ['coder', 'account', 'created', 'modified']
        show_change_link = True
        can_delete = False
        extra = 0

    inlines = [ListValueInline]


@admin_register(ListValue)
class ListValueAdmin(BaseModelAdmin):
    list_display = ['id', 'coder_list', 'group', 'coder', 'account']
    search_fields = ['coder_list__name', 'coder_list__uuid', 'coder__username', 'account__key', 'account__name']
