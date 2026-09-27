from typing import ClassVar

from django.contrib import admin

from events.models import Participant
from pyclist.admin import BaseModelAdmin, admin_register
from true_coders.models import (
    Coder,
    CoderList,
    CoderProblem,
    Filter,
    ListGroup,
    ListProblem,
    ListValue,
    Organization,
    Party,
)


@admin_register(Coder)
class CoderAdmin(BaseModelAdmin):
    search_fields: ClassVar = ["username", "settings"]
    list_display: ClassVar = ["username", "global_rating", "last_activity", "settings"]
    list_filter: ClassVar = ["party", "account__resource"]

    def get_readonly_fields(self, request, obj=None):
        return [
            "n_accounts",
            "n_contests",
            "n_subscribers",
            "n_listvalues",
            "last_activity",
            *super().get_readonly_fields(request, obj),
        ]

    def clean_settings(self, request, queryset):
        count = 0
        for c in queryset:
            if "hide_in_calendar" in c.settings:
                c.settings.pop("hide_in_calendar")
                c.save()
                count += 1
        self.message_user(request, f"{count:d} cleaned.")

    clean_settings.short_description = "Clean selected settings"
    actions: ClassVar = [clean_settings]

    class PartySet(admin.TabularInline):
        model = Party.coders.through
        extra = 0

    inlines: ClassVar = [PartySet]


@admin_register(CoderProblem)
class CoderProblemAdmin(BaseModelAdmin):
    list_display: ClassVar = ["coder", "problem", "verdict", "created", "modified"]
    list_filter: ClassVar = ["verdict", "problem__resource"]
    search_fields: ClassVar = ["coder__username", "problem__name"]


@admin_register(Party)
class PartyAdmin(BaseModelAdmin):
    list_display: ClassVar = ["name", "slug", "contests_count", "coders_count"]
    search_fields: ClassVar = ["name"]
    prepopulated_fields: ClassVar = {"slug": ("name",)}

    def contests_count(self, inst):
        return inst.rating_set.count()

    contests_count.admin_order_field = "contests_count"

    def coders_count(self, inst):
        return inst.coders.count()

    coders_count.admin_order_field = "coders_count"


@admin_register(Filter)
class FilterAdmin(BaseModelAdmin):
    search_fields: ClassVar = ["coder__user__username", "name"]
    list_display: ClassVar = [
        "coder",
        "enabled",
        "name",
        "to_show",
        "regex",
        "inverse_regex",
        "_n_resources",
        "contest_id",
        "categories",
        "created",
        "modified",
    ]
    list_filter: ClassVar = ["enabled"]

    def _n_resources(self, obj):
        return len(obj.resources)


@admin_register(Organization)
class OrganizationAdmin(BaseModelAdmin):
    list_display: ClassVar = ["name", "abbreviation", "name_ru", "participants_count", "author"]
    search_fields: ClassVar = ["name", "abbreviation", "name_ru"]

    def participants_count(self, inst):
        return inst.participant_set.count()

    participants_count.admin_order_field = "participants_count"

    class ParticipantInline(admin.StackedInline):
        model = Participant
        fields: ClassVar = ["is_coach"]
        show_change_link = True
        can_delete = False
        extra = 0

    inlines: ClassVar = [ParticipantInline]


@admin_register(CoderList)
class CoderListAdmin(BaseModelAdmin):
    list_display: ClassVar = ["name", "owner", "access_level", "locale", "uuid"]
    list_filter: ClassVar = ["access_level", "locale"]
    search_fields: ClassVar = ["name", "owner__username", "uuid"]

    def get_readonly_fields(self, request, obj=None):
        return ["uuid", *super().get_readonly_fields(request, obj)]

    class ListGroupInline(admin.TabularInline):
        model = ListGroup
        fields: ClassVar = ["id", "name", "created", "modified"]
        readonly_fields: ClassVar = ["name", "created", "modified"]
        show_change_link = True
        can_delete = False
        extra = 0

    class ListProblemInline(admin.TabularInline):
        model = ListProblem
        fields: ClassVar = ["id", "problem"]
        readonly_fields: ClassVar = ["problem", "created", "modified"]
        show_change_link = True
        can_delete = False
        extra = 0

    inlines: ClassVar = [ListGroupInline, ListProblemInline]


@admin_register(ListGroup)
class ListGroupAdmin(BaseModelAdmin):
    list_display: ClassVar = ["id", "coder_list"]
    search_fields: ClassVar = ["coder_list__name", "coder_list__uuid"]

    class ListValueInline(admin.TabularInline):
        model = ListValue
        fields: ClassVar = ["coder", "account", "created", "modified"]
        readonly_fields: ClassVar = ["coder", "account", "created", "modified"]
        show_change_link = True
        can_delete = False
        extra = 0

    inlines: ClassVar = [ListValueInline]


@admin_register(ListValue)
class ListValueAdmin(BaseModelAdmin):
    list_display: ClassVar = ["id", "coder_list", "group", "coder", "account"]
    search_fields: ClassVar = [
        "coder_list__name",
        "coder_list__uuid",
        "coder__username",
        "account__key",
        "account__name",
    ]
