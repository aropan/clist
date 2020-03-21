import time

from django.core.management.base import BaseCommand
from django.utils.timezone import now
from django.template.loader import get_template
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from datetime import timedelta
from events.models import Team, Event, TeamStatus

import tqdm


class Command(BaseCommand):
    help = 'Event mailing'

    def add_arguments(self, parser):
        parser.add_argument('--event', type=str, required=True)
        parser.add_argument('--status', type=str, required=True)
        parser.add_argument('--dryrun', action='store_true', default=False)
        parser.add_argument('--template', type=str, required=True)

    def handle(self, *args, **options):
        event = Event.objects.filter(name__regex=options['event']).order_by('-created').first()
        self.stdout.write(f'event = {event}')
        template = get_template(options['template'])
        status = getattr(TeamStatus, options['status'].upper())

        teams = Team.objects.filter(
            modified__lt=now() - timedelta(minutes=2),
            event=event,
            status=status,
        )

        n_attempet = 3
        failed = 0
        done = 0
        time_wait_on_success = 2
        time_wait_on_failed = 10

        with event.email_backend() as connection:
            logins = [team.login_set.get(stage=status) for team in teams]
            for team, login in tqdm.tqdm(zip(teams, logins), total=len(logins)):
                message = template.render({'team': team, 'login': login})
                subject, message = message.split('\n\n', 1)
                message = message.replace('\n', '<br>\n')
                to = [settings.ADMINS[0][1]] if options['dryrun'] else [m.email for m in team.ordered_participants]

                msg = EmailMultiAlternatives(
                    subject,
                    message,
                    to=to,
                    connection=connection,
                )
                msg.attach_alternative(message, 'text/html')

                for i in range(n_attempet):
                    result = msg.send()
                    if result:
                        done += 1
                        time.sleep(time_wait_on_success)
                        break
                    time.sleep(time_wait_on_failed)
                else:
                    failed += 1
                if options['dryrun']:
                    break

        self.stdout.write(f'Successfully mailing: {done} of {teams.count()} ({failed} fails)')
