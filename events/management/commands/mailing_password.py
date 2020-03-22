import os
import time
from datetime import timedelta

import yaml
import tqdm
import arrow
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import OuterRef, Exists, Q

from events.models import Team, Event, TeamStatus, Login
from utils.yac import change_names


class Command(BaseCommand):
    help = 'Mailing password'

    def add_arguments(self, parser):
        parser.add_argument('--event', type=str, required=True)
        parser.add_argument('--status', type=str, required=True)
        parser.add_argument('--ya-contest-id', type=int, help='Contest id for change names')
        parser.add_argument('--dryrun', action='store_true', default=False)
        parser.add_argument('--conf-file', default=os.path.join(os.path.dirname(__file__), 'mailing_password.yaml'))

    def handle(self, *args, **options):
        conf_file = options['conf_file']
        if os.path.exists(conf_file):
            with open(options['conf_file'], 'r') as fo:
                conf = yaml.safe_load(fo)
        else:
            conf = {}

        event = Event.objects.filter(name__regex=options['event']).order_by('-created').first()
        self.stdout.write(f'event = {event}')
        status = getattr(TeamStatus, options['status'].upper())

        event = Event.objects.order_by('-created').first()
        logins_subquery = Login.objects.filter(team=OuterRef('pk'))
        teams = Team.objects \
            .filter(modified__lt=timezone.now() - timedelta(minutes=15), event=event, status=status) \
            .annotate(has_login=Exists(logins_subquery)) \
            .filter(has_login=False)

        cache = {}
        done = 0
        if not options['dryrun']:
            for t in tqdm.tqdm(teams):
                created, login = t.attach_login(cache=cache)
                if created:
                    done += 1
        self.stdout.write(f'Successfully attach login: {done} of {teams.count()}')

        logins = Login.objects.filter(is_sent=False, team__event=event)

        n_attempet = 3
        failed = 0
        done = 0
        time_wait_on_success = 2
        time_wait_on_failed = 10
        if not options['dryrun']:
            with event.email_backend() as connection:
                for login in tqdm.tqdm(logins):
                    for i in range(n_attempet):
                        if login.send_email(connection=connection):
                            done += 1
                            time.sleep(time_wait_on_success)
                            break
                        time.sleep(time_wait_on_failed)
                    else:
                        failed += 1
        self.stdout.write(f'Successfully mailing: {done} of {logins.count()} ({failed} fails)')

        if options['ya_contest_id']:
            logins = Login.objects.filter(is_sent=True, team__event=event)
            filter_time = conf.get('change_names_last_update_time')
            if not options['dryrun']:
                conf['change_names_last_update_time'] = timezone.now()
            if filter_time:
                filter_time = arrow.get(filter_time).format()
                logins = logins.filter(
                    Q(team__modified__gte=filter_time) |
                    Q(team__participants__modified__gte=filter_time) |
                    Q(team__participants__organization__modified__gte=filter_time)
                ).distinct('pk')
            names = []
            for login in logins:
                names.append({'login': login.username, 'name': login.team.title})
            if names and not options['dryrun']:
                result = change_names(contest_id=options['ya_contest_id'], names=names)
            else:
                result = ''
            self.stdout.write(f'Change names for {len(names)} team(s) = {result}')

        with open(options['conf_file'], 'w') as fo:
            yaml.dump(conf, fo, indent=2)
