#!/usr/bin/env python3

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

PRODUCTION_ERROR = "dump_parser_fixture is a development-only command; run it through the dev service"


if settings.ENVIRONMENT == settings.PROD_ENV:

    class Command(BaseCommand):
        help = "Record or update an offline parser regression fixture"

        def run_from_argv(self, argv):
            self.stderr.write(self.style.ERROR(f"CommandError: {PRODUCTION_ERROR}"))
            raise SystemExit(1)

        def handle(self, *args, **options):
            raise CommandError(PRODUCTION_ERROR)

else:
    from ranking.tests.parser_fixture_command import Command as Command
