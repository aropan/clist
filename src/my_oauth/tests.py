from io import StringIO
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


class CreateAdminTest(TestCase):
    def test_reads_password_from_stdin(self):
        with patch("sys.stdin", StringIO("admin-secret\n")):
            call_command(
                "createadmin",
                username="admin",
                email="admin@example.com",
                password_stdin=True,
                interactive=False,
                stdout=StringIO(),
            )

        assert User.objects.get(username="admin").check_password("admin-secret")

    def test_keeps_password_argument_compatible(self):
        call_command(
            "createadmin",
            username="admin",
            email="admin@example.com",
            password="admin-secret",
            interactive=False,
            stdout=StringIO(),
        )

        assert User.objects.get(username="admin").check_password("admin-secret")

    def test_rejects_empty_stdin_password(self):
        with patch("sys.stdin", StringIO("")), pytest.raises(CommandError):
            call_command(
                "createadmin",
                username="admin",
                email="admin@example.com",
                password_stdin=True,
                interactive=False,
                stdout=StringIO(),
            )
