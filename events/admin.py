import time

import unicodecsv as csv
from django.contrib import admin
from django.db.models import Exists, OuterRef, Q
from django.http import HttpResponse
from django.utils import timezone
from django_print_sql import print_sql_decorator

from events.models import Event, JoinRequest, Login, Participant, Team, TeamStatus
from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(Event)
class EventAdmin(BaseModelAdmin):
    list_display = ['name', 'slug', 'participants_count', 'teams_count', 'registration_deadline']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name', )}
    textarea_fields = ['information']

    def participants_count(self, inst):
        return inst.participant_set.count()

    def teams_count(self, inst):
        return inst.team_set.count()


@admin_register(Participant)
class ParticipantAdmin(BaseModelAdmin):
    search_fields = ['coder__user__username', 'first_name', 'last_name', 'email', 'team__name']
    list_display = [
        'coder',
        'first_name',
        'last_name',
        'email',
        'is_coach',
    ]

    class HasTeamFilter(admin.SimpleListFilter):
        title = 'has registered team'
        parameter_name = 'has_registered_team'

        def lookups(self, request, model_admin):
            return (
                ('yes', 'Yes'),
                ('no', 'No'),
            )

        def queryset(self, request, queryset):
            if self.value() in ['yes', 'no']:
                new_statuses = [k for k, v in TeamStatus.descriptions.items() if v == 'new']
                cond = Q()
                for status in new_statuses:
                    cond |= Q(team__status=status)
                cond |= Q(team__isnull=True)
                if self.value() == 'yes':
                    queryset = queryset.exclude(cond)
                else:
                    queryset = queryset.filter(cond)
            return queryset

    list_filter = ['event', 'is_coach', HasTeamFilter, 'organization', 'country']

    @print_sql_decorator(count_only=True)
    def import_to_csv(self, request, queryset):
        queryset = queryset.select_related('team')
        filename = 'participants-{}.csv'.format(timezone.now().strftime('%Y%m%d%H%M'))
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=%s' % filename
        encoding = 'cp1251' if request.user_agent.os.family == 'Windows' else 'utf8'
        writer = csv.writer(response, delimiter=';', encoding=encoding, errors='replace')
        fields = [
            'email',
            'first_name',
            'last_name',
            'first_name_native',
            'last_name_native',
            'middle_name_native',
            'phone_number',
            'organization',
            'country',
            'tshirt_size_value',
            'is_coach',
        ]
        writer.writerow(['title'] + [f.replace('_', ' ').title() for f in fields])
        for member in queryset:
            values = [member.team.name if member.team else ''] + [str(getattr(member, f)) for f in fields]
            writer.writerow(values)
        return response
    import_to_csv.short_description = 'Import to csv'

    actions = [import_to_csv]


@admin_register(JoinRequest)
class JoinRequestAdmin(BaseModelAdmin):
    list_display = ['team', 'participant', 'created']
    search_fields = ['team', 'participant']


class TeamHasLoginFilter(admin.SimpleListFilter):
    title = 'has login'
    parameter_name = 'has_login'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Yes'),
            ('no', 'No'),
        )

    def queryset(self, request, queryset):
        if self.value() in ['yes', 'no']:
            logins = Login.objects.filter(team=OuterRef('pk'), stage=OuterRef('status'))
            queryset = queryset.annotate(has_login=Exists(logins))
            queryset = queryset.filter(has_login=self.value() == 'yes')
        return queryset


@admin_register(Team)
class TeamAdmin(BaseModelAdmin):
    list_display = ['name', 'event', 'status', 'coach', 'participants_count', 'author']
    search_fields = ['name', 'coach__last_name']
    list_filter = [TeamHasLoginFilter, 'status', 'event']

    def participants_count(self, inst):
        return inst.participants_count
    participants_count.admin_order_field = 'participants_count'

    def bind_login(self, request, queryset):
        skip = 0
        done = 0
        cache = {}
        for team in queryset:
            created, _ = team.attach_login(cache=cache)
            if created:
                done += 1
            else:
                skip += 1
        self.message_user(request, '{} successfully created logins, {} skipped.'.format(done, skip))
    bind_login.short_description = 'Bind login with current status as stage'

    @print_sql_decorator(count_only=True)
    def import_to_csv(self, request, queryset):
        filename = 'teams-{}.csv'.format(timezone.now().strftime('%Y%m%d%H%M'))
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=%s' % filename
        encoding = 'cp1251' if request.user_agent.os.family == 'Windows' else 'utf8'
        writer = csv.writer(response, delimiter=';', encoding=encoding, errors='replace')
        fields = [
            'email',
            'first_name',
            'last_name',
            'first_name_native',
            'last_name_native',
            'middle_name_native',
            'phone_number',
            'organization',
            'country',
            'tshirt_size_value',
            'is_coach',
        ]
        writer.writerow(['title'] + [f.replace('_', ' ').title() for f in fields])
        for team in queryset:
            for m in team.members:
                values = [team.title] + [str(getattr(m, f)) for f in fields]
                writer.writerow(values)
        return response
    import_to_csv.short_description = 'Import to csv'

    actions = [bind_login, import_to_csv]


@admin_register(Login)
class LoginAdmin(BaseModelAdmin):
    list_display = ['team', 'stage', 'username', 'password', 'is_sent']
    search_fields = ['team__name', 'username', 'stage']
    list_filter = ['stage', 'is_sent', 'team__event']

    def get_renaming_data(self, request, queryset):
        response = HttpResponse(content_type='text')
        response['Content-Disposition'] = 'attachment; filename=namming.txt'
        for login in queryset:
            response.write('{} {}\n'.format(login.username, login.team.title))
        return response
    get_renaming_data.short_description = 'Get raw data for renameing teams'

    def get_passwords(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=passwords.csv'
        for login in queryset:
            response.write('{},{},{}\n'.format(login.username, login.password, login.team.title))
        return response
    get_passwords.short_description = 'Get passwords'

    def send_email(self, request, queryset):
        n_attempet = 5
        time_wait_on_failed = 10

        cache = {}

        skip = 0
        done = 0
        failed = 0
        for login in queryset:
            if login.is_sent:
                skip += 1
                continue
            event = login.team.event
            if event.pk not in cache:
                cache[event.pk] = event.email_backend().__enter__()

            for i in range(n_attempet):
                if login.send_email(connection=cache[event.pk]):
                    done += 1
                    time.sleep(2)
                    break
                time.sleep(time_wait_on_failed)
            else:
                failed += 1

        for connection in list(cache.values()):
            connection.close()

        self.message_user(request, '{} successfully send emails, {} skipped, {} failed.'.format(done, skip, failed))
    send_email.short_description = 'Send email with template message by stage'

    actions = [send_email, get_renaming_data, get_passwords]
