from pyclist.admin import BaseModelAdmin, admin_register
from django.contrib import admin
from true_coders.models import Coder, Filter, Party, Organization
from events.models import Participant


@admin_register(Coder)
class CoderAdmin(BaseModelAdmin):
    search_fields = ['username', 'settings']
    list_display = ['username', 'timezone', 'settings']
    list_filter = ['party', 'account__resource']

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
        'name',
        'to_show',
        'regex',
        'inverse_regex',
        'resources',
        'categories',
        'modified',
    ]


@admin_register(Organization)
class OrganizationAdmin(BaseModelAdmin):
    list_display = ['name', 'abbreviation', 'name_ru', 'participants_count', 'author']
    search_fields = ['name', 'abbreviation', 'name_ru']

    def participants_count(self, inst):
        return inst.participant_set.count()
    participants_count.admin_order_field = 'participants_count'

    class ParticipantInline(admin.StackedInline):
        model = Participant
        fields = ['organization']
        show_change_link = True
        can_delete = False
        extra = 0
    inlines = [ParticipantInline]
