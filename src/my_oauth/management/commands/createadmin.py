#!/usr/bin/env python3

import sys

from django.contrib.auth.management.commands.createsuperuser import Command as SuperUserCommand
from django.contrib.auth.models import User
from django.core.management.base import CommandError

from true_coders.models import Coder


class Command(SuperUserCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument("--password", type=str, help="Specifies the password for the superuser.")
        parser.add_argument("--password-stdin", action="store_true", help="Read the password from standard input.")

    def handle(self, *args, **options):
        username = options["username"]
        if options["password_stdin"] and options["password"] is not None:
            raise CommandError("Use only one of --password and --password-stdin.")
        password = sys.stdin.readline().rstrip("\r\n") if options["password_stdin"] else options["password"]
        if not password:
            raise CommandError("A non-empty password is required.")
        super().handle(*args, **options)
        user = User.objects.get(username=username)
        coder = Coder.objects.create(user=user, username=username)
        user.set_password(password)
        user.coder = coder
        user.save()
