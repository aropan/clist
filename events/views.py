from collections import Counter

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect, resolve_url
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.mail import EmailMessage
from django.views.decorators.clickjacking import xframe_options_exempt
from django.utils.timezone import now, timedelta
from django.template.loader import get_template
from django_countries import countries
from django.views.decorators.cache import cache_page

from el_pagination.decorators import page_templates

from events.models import Event, Participant, Team, JoinRequest, TeamStatus, TshirtSize
from true_coders.models import Organization
import true_coders.views

import humanfriendly


def events(request):
    return render(
        request,
        'events.html',
        {
            'events': Event.objects.order_by('-created'),
        },
    )


@page_templates((
    ('team-participants.html', 'teams'),
    ('participants.html', 'participants'),
    ('team-participants-admin.html', 'teams-admin'),
))
def event(request, slug, template='event.html', extra_context=None):
    event = get_object_or_404(Event, slug=slug)
    user = request.user
    coder = None if user.is_anonymous else user.coder
    participant = event.participant_set.filter(coder=coder, coder__isnull=False).first()
    if participant:
        join_requests = participant.joinrequest_set.all()
        team = event.team_set \
            .filter(participants__pk=participant.pk) \
            .prefetch_related('joinrequest_set', 'participants') \
            .first()
    else:
        join_requests = None
        team = None

    end_registration = event.registration_deadline < now()
    registration_timeleft = event.registration_deadline - now()
    if coder and coder.settings.get('unlimited_deadline'):
        registration_timeleft = timedelta(minutes=42)
        end_registration = False

    query = request.POST.get('query') or request.GET.get('query')
    if query is not None and not end_registration:
        if query == 'skip-coach':
            if not team or team.author != participant:
                messages.error(request, 'First you need to create a team')
            elif team.status != TeamStatus.ADD_COACH:
                messages.error(request, 'Not necessary skip coach')
            else:
                team.status = TeamStatus.PENDING
                team.save()
        elif query in ['join', 'add-coach']:  # 'join-as-coach'
            is_coach = query == 'add-coach'
            ok = True
            if not is_coach and participant:
                messages.info(request, 'You have already joined the event')
                ok = False
            if is_coach and (not team or team.status != TeamStatus.ADD_COACH):
                messages.error(request, 'First you need to create a team')
                ok = False
            else:
                active_fields = [
                    'first-name',
                    'last-name',
                    'email',
                    'first-name-native',
                    'last-name-native',
                    'phone-number',
                    'tshirt-size',
                ]
                if not is_coach:
                    active_fields.append('organization')
                    active_fields.append('country')
                for field in active_fields:
                    if not request.POST.get(field, ''):
                        messages.error(request, 'You must specify all the information')
                        ok = False
                        break
                else:
                    if not is_coach and not coder.token_set.filter(email=request.POST['email']).exists():
                        messages.error(request, 'Invalid email. Check that the account with this email is connected')
                        ok = False
                active_fields.append('middle-name-native')
            if ok:
                if is_coach:
                    participant = Participant.objects.create(event=event, is_coach=True)
                else:
                    participant, _ = Participant.objects.get_or_create(coder=coder, event=event)

                created = False

                try:
                    data = dict(list(request.POST.items()))
                    if 'organization' in data:
                        organization_name = data['organization']
                        organization, created = Organization.objects.get_or_create(name=organization_name)
                        if created:
                            organization.name_ru = organization_name
                            organization.author = coder
                            organization.save()
                        data['organization'] = organization

                    for object_, attr in (
                        (user, 'first_name'),
                        (user, 'last_name'),
                        (user, 'email'),
                        (coder, 'first_name_native'),
                        (coder, 'last_name_native'),
                        (coder, 'middle_name_native'),
                        (coder, 'phone_number'),
                        (coder, 'country'),
                        (coder, 'organization'),
                        (None, 'tshirt_size'),
                    ):
                        field = attr.replace('_', '-')
                        if field not in active_fields:
                            continue
                        value = data[field]
                        if not is_coach and object_:
                            setattr(object_, attr, value or getattr(object_, attr))
                        setattr(participant, attr, value)
                    participant.save()
                    user.save()
                    coder.save()
                    if is_coach:
                        team.coach = participant
                        team.status = TeamStatus.PENDING
                        team.save()
                except Exception:
                    participant.delete()
                    if created:
                        organization.delete()
                    raise
        elif query == 'create-team':
            team_name = request.POST.get('team')
            if not team_name:
                messages.error(request, 'You must specify team name')
            elif participant and participant.is_coach:
                team = Team.objects.create(event=event, name=team_name, author=participant)
                team.coach = participant
                team.save()
            elif team or join_requests:
                messages.error(request, 'You have already committed an action')
            else:
                team = Team.objects.create(event=event, name=team_name, author=participant)
                team.participants.add(participant)
                team.save()
        elif query == 'join-team':
            is_coach = participant and participant.is_coach
            if not is_coach and (team or join_requests):
                messages.error(request, 'You have already committed an action')
            else:
                team_id = int(request.POST.get('team'))
                team = Team.objects.get(pk=team_id, event=event, status=TeamStatus.NEW)
                if not JoinRequest.objects.filter(team=team, participant=participant).exists():
                    JoinRequest.objects.create(team=team, participant=participant)
        elif query == 'cancel-request':
            if not join_requests:
                messages.error(request, 'Join request not found')
            else:
                join_request_id = int(request.GET.get('request_id'))
                JoinRequest.objects.filter(pk=join_request_id, participant=participant).delete()
        elif query in ['accept-team', 'reject-team']:
            request_id = int(request.POST.get('request_id'))
            join_request = JoinRequest.objects \
                .filter(pk=request_id) \
                .filter(Q(team__author=participant) | Q(team__coach=participant)) \
                .first()
            if not join_request:
                messages.error(request, 'First you need to create a join request')
            else:
                participant = join_request.participant
                team = join_request.team
                if query == 'accept-team':
                    if participant.is_coach:
                        team.coach = participant
                        team.save()
                    else:
                        team.participants.add(participant)
                join_request.delete()
        elif query in ['register', 'delete-team']:
            team_id = int(request.POST.get('team_id'))
            team = Team.objects \
                .filter(pk=team_id) \
                .filter(Q(author=participant) | Q(coach=participant)) \
                .first()
            if not team:
                messages.error(request, 'First you need to create a team')
            elif team.status != TeamStatus.NEW:
                messages.error(request, 'Team already registered')
            elif query == 'delete-team':
                team.delete()
            elif not 0 < team.participants.count() < 4:
                messages.error(request, 'Team should be consists of one to three participants')
            else:
                if team.coach:
                    team.status = TeamStatus.PENDING
                else:
                    team.status = TeamStatus.ADD_COACH
                team.save()

        return redirect('{}#registration-tab'.format(resolve_url('events:event', slug=event.slug)))

    teams = Team.objects.filter(event=event).order_by('-created')
    teams = teams.prefetch_related(
        'participants__coder__user',
        'participants__organization',
    )
    teams = teams.select_related(
        'author__coder__user',
        'author__organization',
        'coach__coder__user',
        'coach__organization',
    )

    approved_statuses = {k for k, v in TeamStatus.descriptions.items() if v == 'approved'}
    team_participants = teams.filter(status__in=approved_statuses)

    participants = Participant.objects.filter(
        event=event,
        is_coach=False,
    ).filter(
        Q(team=None) | Q(team__status=TeamStatus.NEW),
    ).select_related(
        'coder__user',
    ).all()

    context = {
        'slug': slug,
        'event': event,
        'coder': coder,
        'participant': participant,
        'team_participants': team_participants,
        'participants': participants,
        'team': team,
        'join_requests': join_requests,
        'team_status': TeamStatus,
        'tshirt_size': TshirtSize,
        'teams': teams,
        'defaults': {
            # 'organization': Organization.objects.get(abbreviation='BSUIR').name,
            'country': {'code': 'BY', 'name': dict(countries)['BY']},
        },
        'registration': {
            'over': end_registration,
            'timeleft': humanfriendly.format_timespan(registration_timeleft),
        },
    }

    if extra_context is not None:
        context.update(extra_context)

    return render(request, template, context)


def result(request, slug, name):
    event = get_object_or_404(Event, slug=slug)
    standings_urls = {s['name'].lower(): s['url'] for s in event.standings_urls}
    url = standings_urls[name]
    if url.startswith('http'):
        return redirect(url)
    template = get_template(url)
    html = template.render()
    return HttpResponse(html)


@permission_required('events.change_team')
def team_admin_view(request, slug, team_id):
    event = get_object_or_404(Event, slug=slug)
    team = get_object_or_404(Team, pk=team_id, event=event)

    if 'action' in request.POST:
        action = request.POST.get('action')
        if action == 'change':
            status = request.POST.get('status')
            team_name = request.POST.get('name')
            team.name = team_name
            team.status = int(status)
            team.save()
        elif action == 'email':
            subject = request.POST['subject']
            message = request.POST['message']
            emails = list(map(str.strip, request.POST['emails'].split(',')))
            with event.email_backend() as connection:
                EmailMessage(
                    subject,
                    message,
                    from_email=event.email_conf['from_email'],
                    to=emails,
                    connection=connection,
                ).send()
        return redirect('events:team-details', slug=slug, team_id=team_id)

    return render(
        request,
        'team-admin-view.html',
        {
            'slug': slug,
            'team': team,
            'event': event,
            'team_status': TeamStatus,
            'tshirt_size': TshirtSize,
        },
    )


@cache_page(30 * 60)
@xframe_options_exempt
def frame(request, slug, status):
    event = get_object_or_404(Event, slug=slug)
    statuses = []
    if status == TeamStatus.labels[TeamStatus.SCHOOL_FINAL]:
        statuses.append(TeamStatus.SCHOOL_FINAL)
    elif status == TeamStatus.labels[TeamStatus.FINAL]:
        statuses.append(TeamStatus.INVITED)
        statuses.append(TeamStatus.FINAL)
    else:
        for s in (
            TeamStatus.INVITED,
            TeamStatus.FINAL,
            TeamStatus.SCHOOL_FINAL,
            TeamStatus.BSU_SEMIFINAL,
            TeamStatus.SEMIFINAL,
            TeamStatus.QUARTERFINAL,
            TeamStatus.QUALIFICATION,
            TeamStatus.EDITING,
            TeamStatus.DISQUALIFIED,
        ):
            statuses.append(s)
            if TeamStatus.labels[s] == status:
                break
    teams = Team.objects.filter(event=event, status__in=statuses).order_by('-created')
    countries = Counter(t.country for t in teams)

    return render(
        request,
        'frame-team.html',
        {
            'teams': teams,
            'countries': countries.most_common(),
            'team_status': TeamStatus,
        },
    )


@login_required
def change(request, slug):
    return true_coders.views.change(request)


@login_required
def search(request, slug):
    event = get_object_or_404(Event, slug=slug)
    return true_coders.views.search(request, event=event)
