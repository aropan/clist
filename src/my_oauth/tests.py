from io import StringIO
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from my_oauth.models import Service, Token
from my_oauth.views import process_data, signup
from true_coders.models import Coder


class OAuthAccountLinkingTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="existing-owner", email="shared@example.com")
        self.coder = Coder.objects.create(user=self.owner)
        self.existing_service = Service.objects.create(name="google", user_id_field="id", email_field="email")
        self.new_service = Service.objects.create(name="discord", user_id_field="id", email_field="email")
        self.existing_token = Token.objects.create(
            service=self.existing_service,
            user_id="existing-provider-id",
            coder=self.coder,
            email=self.owner.email,
            data={"verified_email": True},
        )

    def make_request(self, user=None, data=None):
        factory = RequestFactory()
        request = factory.post("/signup/", data) if data else factory.get("/signup/")
        SessionMiddleware(lambda request: HttpResponse()).process_request(request)
        request.user = user or AnonymousUser()
        request.logger = Mock()
        return request

    def receive_identity(self, request, service=None, user_id="new-provider-id", email=None, **data):
        process_data(
            request,
            service or self.new_service,
            {},
            {"id": user_id, "email": email or self.owner.email, **data},
        )
        return Token.objects.get(pk=request.session["token_id"])

    def test_email_match_never_authenticates_or_links_an_anonymous_user(self):
        for index, data in enumerate(({}, {"verified": False}, {"verified": True})):
            with self.subTest(data=data):
                request = self.make_request()
                token = self.receive_identity(request, user_id=f"new-provider-{index}", **data)

                with patch("my_oauth.views.render", return_value=HttpResponse()) as render:
                    signup(request)

                token.refresh_from_db()
                assert token.coder_id is None
                assert request.user.is_anonymous
                assert SESSION_KEY not in request.session
                assert request.session["token_id"] == token.pk
                assert self.existing_token in render.call_args.args[2]["tokens"]

    def test_verified_identity_does_not_log_into_an_unverified_email_owner(self):
        self.existing_token.data = {"verified_email": False}
        self.existing_token.save()
        request = self.make_request()
        token = self.receive_identity(request, verified=True)

        with patch("my_oauth.views.render", return_value=HttpResponse()):
            signup(request)

        token.refresh_from_db()
        assert token.coder_id is None
        assert SESSION_KEY not in request.session

    def test_authenticated_user_can_link_a_service_despite_another_users_email_match(self):
        user = User.objects.create_user(username="linking-owner")
        coder = Coder.objects.create(user=user)
        request = self.make_request(user=user)
        token = self.receive_identity(request, verified=False)

        response = signup(request)

        token.refresh_from_db()
        assert response.status_code == 302
        assert token.coder_id == coder.pk
        assert request.user.pk == user.pk
        assert SESSION_KEY not in request.session

    def test_linked_identity_still_logs_in_after_its_email_changes(self):
        request = self.make_request()
        token = self.receive_identity(
            request,
            service=self.existing_service,
            user_id=self.existing_token.user_id,
            email="changed@example.com",
            verified_email=False,
        )

        response = signup(request)

        token.refresh_from_db()
        assert response.status_code == 302
        assert token.pk == self.existing_token.pk
        assert token.coder_id == self.coder.pk
        assert request.user.pk == self.owner.pk
        assert request.session[SESSION_KEY] == str(self.owner.pk)

    def test_new_registration_with_matching_email_does_not_take_over_existing_account(self):
        request = self.make_request(data={"signup": "", "username": "new-owner"})
        token = self.receive_identity(request, verified=False)

        response = signup(request)

        token.refresh_from_db()
        self.existing_token.refresh_from_db()
        assert response.status_code == 302
        assert request.user.username == "new-owner"
        assert token.coder_id != self.coder.pk
        assert self.existing_token.coder_id == self.coder.pk
        assert User.objects.count() == 2


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
