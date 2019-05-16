import time

from django.core.management.base import BaseCommand
from django.utils.timezone import now
from datetime import timedelta
from events.models import Team, Event, TeamStatus, Login

import tqdm


class Command(BaseCommand):
    help = 'Mailing password'

    def handle(self, *args, **options):
        event = Event.objects.order_by('-created').first()
        teams = Team.objects.filter(
            modified__lt=now() - timedelta(minutes=2),
            event=event,
            status=TeamStatus.SEMIFINAL,
        )
        cache = {}
        done = 0
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
