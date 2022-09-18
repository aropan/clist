#!/usr/bin/env python3


from django.contrib.auth.management.commands.createsuperuser import Command as SuperUserCommand
from django.contrib.auth.models import User

from true_coders.models import Coder


class Command(SuperUserCommand):

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument('--password', type=str, required=True, help='Specifies the password for the superuser.')

    def handle(self, *args, **options):
        username = options['username']
        password = options['password']
        super().handle(*args, **options)
        user = User.objects.get(username=username)
        coder = Coder.objects.create(user=user, username=username)
        user.set_password(password)
        user.coder = coder
        user.save()
