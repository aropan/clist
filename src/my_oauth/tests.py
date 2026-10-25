from functools import partial
from io import StringIO
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase, override_settings
from lxml import html

from my_oauth.models import Service, Token
from my_oauth.views import LAST_OAUTH_PROVIDER_COOKIE, login, process_data, signup
from true_coders.models import Coder
from utils.custom_request import set_security_cookie


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
        request.set_security_cookie = partial(set_security_cookie, request)
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
                    response = signup(request)

                assert LAST_OAUTH_PROVIDER_COOKIE not in response.cookies
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
        request.COOKIES[LAST_OAUTH_PROVIDER_COOKIE] = "google"
        token = self.receive_identity(request, verified=False)

        response = signup(request)

        token.refresh_from_db()
        assert response.status_code == 302
        assert token.coder_id == coder.pk
        assert request.user.pk == user.pk
        assert SESSION_KEY not in request.session
        assert LAST_OAUTH_PROVIDER_COOKIE not in response.cookies

    def test_incomplete_signup_and_inactive_account_do_not_change_hint(self):
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        incomplete_token = Token.objects.create(service=self.new_service, user_id="pending", email="new@example.com")
        for token in (self.existing_token, incomplete_token):
            for previous_provider in (None, "discord"):
                with self.subTest(token=token.pk, previous_provider=previous_provider):
                    request = self.make_request()
                    if previous_provider:
                        request.COOKIES[LAST_OAUTH_PROVIDER_COOKIE] = previous_provider
                    request.session["token_id"] = token.pk

                    with patch("my_oauth.views.render", return_value=HttpResponse()):
                        response = signup(request)

                    assert request.user.is_anonymous
                    assert LAST_OAUTH_PROVIDER_COOKIE not in response.cookies

    def test_authenticated_reauthentication_does_not_change_hint(self):
        for previous_provider in (None, "discord"):
            with self.subTest(previous_provider=previous_provider):
                request = self.make_request(user=self.owner)
                if previous_provider:
                    request.COOKIES[LAST_OAUTH_PROVIDER_COOKIE] = previous_provider
                request.session["token_id"] = self.existing_token.pk

                response = signup(request)

                assert response.status_code == 302
                assert LAST_OAUTH_PROVIDER_COOKIE not in response.cookies

    def test_provider_selection_and_failed_callbacks_do_not_change_hint(self):
        self.existing_service.code_uri = "https://provider.example/authorize?state=%(state)s"
        self.existing_service.save(update_fields=["code_uri"])
        for previous_provider in (None, "discord"):
            with self.subTest(previous_provider=previous_provider):
                if previous_provider:
                    self.client.cookies[LAST_OAUTH_PROVIDER_COOKIE] = previous_provider
                response = self.client.post("/login/", {"service": "google"})
                assert response.status_code == 302
                assert LAST_OAUTH_PROVIDER_COOKIE not in response.cookies

                for callback in ({"state": "wrong"}, {"state": "test-state", "error": "access_denied"}):
                    session = self.client.session
                    session["state"] = "test-state"
                    session.save()
                    response = self.client.get("/oauth/google/response/", callback)
                    assert response.status_code == 302
                    assert LAST_OAUTH_PROVIDER_COOKIE not in response.cookies
                    assert SESSION_KEY not in self.client.session

    def test_password_fallback_does_not_change_hint(self):
        Service.objects.update(disable=True)
        self.owner.set_password("test-password")
        self.owner.save(update_fields=["password"])
        for previous_provider in (None, "google"):
            with self.subTest(previous_provider=previous_provider):
                request = self.make_request(
                    data={"action": "login", "username": self.owner.username, "password": "test-password"}
                )
                request.GET = RequestFactory().get("/login/", {"next": "/"}).GET
                if previous_provider:
                    request.COOKIES[LAST_OAUTH_PROVIDER_COOKIE] = previous_provider

                response = login(request)

                assert response.status_code == 302
                assert request.user.pk == self.owner.pk
                assert LAST_OAUTH_PROVIDER_COOKIE not in response.cookies

    def test_linked_identity_still_logs_in_after_its_email_changes(self):
        request = self.make_request()
        request.session["next"] = "/settings/social/"
        request.session.set_expiry(3600)
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
        assert response.url == "/settings/social/"
        assert request.session.get_expiry_age() == 3600
        self.assert_provider_cookie(response, "google")

    def assert_provider_cookie(self, response, provider):
        cookie = response.cookies[LAST_OAUTH_PROVIDER_COOKIE]
        assert cookie.value == provider
        assert cookie["max-age"] == 365 * 24 * 60 * 60
        assert cookie["expires"]
        assert cookie["path"] == "/login/"
        assert not cookie["domain"]
        assert cookie["httponly"]
        assert cookie["secure"]
        assert cookie["samesite"] == "Lax"

    def test_successful_login_replaces_or_renews_the_provider_cookie(self):
        for previous_provider in ("discord", "google"):
            with self.subTest(previous_provider=previous_provider):
                request = self.make_request()
                request.COOKIES[LAST_OAUTH_PROVIDER_COOKIE] = previous_provider
                request.session["token_id"] = self.existing_token.pk

                response = signup(request)

                self.assert_provider_cookie(response, "google")
                assert request.user.pk == self.owner.pk

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
        self.assert_provider_cookie(response, "discord")


@override_settings(DEBUG_PERMISSION_EXCLUDE_PATHS={"login", "signup", "logout"})
class OAuthLoginProviderHintTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="login-hint-user")
        cls.coder = Coder.objects.create(user=cls.user)
        cls.google = Service.objects.create(
            name="google",
            title="Google",
            user_id_field="id",
            code_uri="https://google.example/authorize?state=%(state)s",
        )
        cls.github = Service.objects.create(
            name="github",
            title="GitHub",
            user_id_field="id",
            code_uri="https://github.example/authorize?state=%(state)s",
        )
        cls.google_token = Token.objects.create(service=cls.google, user_id="google-user", coder=cls.coder)
        cls.github_token = Token.objects.create(service=cls.github, user_id="github-user", coder=cls.coder)
        Token.objects.create(service=cls.google, user_id="another-google-user")

    def test_hint_marks_only_matching_provider_without_reordering_or_selecting(self):
        baseline = self.client.get("/login/")
        self.assertNotContains(baseline, "Last used")
        self.client.cookies[LAST_OAUTH_PROVIDER_COOKIE] = "github"

        response = self.client.get("/login/")

        self.assertContains(response, "Last used", count=1)
        assert response.context["last_oauth_provider"] == "github"
        assert response.wsgi_request.user.is_anonymous
        assert LAST_OAUTH_PROVIDER_COOKIE not in response.cookies
        document = html.fromstring(response.content)
        buttons = document.xpath("//a[@data-service]")
        assert [button.get("data-service") for button in buttons] == ["google", "github"]
        badge = document.xpath('//span[@class="login-service-last-used"]')[0]
        assert badge.xpath("ancestor::a/@data-service") == ["github"]
        assert badge.get("title") == "Last successful sign-in in this browser"
        assert buttons[1].get("aria-describedby") == "last-oauth-provider-description"
        assert document.get_element_by_id("last-oauth-provider-description").text == badge.get("title")
        assert not document.xpath('//input[@name="service"]')[0].get("value")
        baseline_form = html.fromstring(baseline.content)
        assert html.tostring(document.get_element_by_id("session_duration")) == html.tostring(
            baseline_form.get_element_by_id("session_duration")
        )

    def test_missing_unknown_and_malformed_hints_are_ignored(self):
        for provider in (None, "", "missing-provider", '<script>alert("provider")</script>'):
            with self.subTest(provider=provider):
                if provider is not None:
                    self.client.cookies[LAST_OAUTH_PROVIDER_COOKIE] = provider
                response = self.client.get("/login/")
                self.assertNotContains(response, "Last used")
                assert response.context["last_oauth_provider"] is None
                assert LAST_OAUTH_PROVIDER_COOKIE not in response.cookies
                self.assertNotContains(response, 'alert("provider")')

    def test_disabled_and_removed_providers_are_not_shown(self):
        self.client.cookies[LAST_OAUTH_PROVIDER_COOKIE] = "github"
        self.github.disable = True
        self.github.save(update_fields=["disable"])
        response = self.client.get("/login/")
        self.assertNotContains(response, 'data-service="github"')
        self.assertNotContains(response, "Last used")

        self.github.delete()
        response = self.client.get("/login/")
        self.assertNotContains(response, 'data-service="github"')
        self.assertNotContains(response, "Last used")

    def complete_login(self, client, token):
        response = client.post("/login/", {"service": token.service.name})
        assert response.status_code == 302
        assert LAST_OAUTH_PROVIDER_COOKIE not in response.cookies
        session = client.session
        session["token_id"] = token.pk
        session["next"] = "/"
        session.save()
        response = client.get("/signup/")
        assert response.status_code == 302
        assert response.url == "/"
        assert response.cookies[LAST_OAUTH_PROVIDER_COOKIE].value == token.service.name
        assert client.session[SESSION_KEY] == str(token.coder.user_id)
        return response

    def test_logout_and_session_expiry_preserve_hint(self):
        for ending in ("logout", "expiry"):
            with self.subTest(ending=ending):
                client = Client()
                self.complete_login(client, self.google_token)
                if ending == "logout":
                    response = client.get("/logout/")
                    assert response.status_code == 302
                    assert LAST_OAUTH_PROVIDER_COOKIE not in response.cookies
                else:
                    session = client.session
                    session.set_expiry(-1)
                    session.save()

                response = client.get("/login/")

                self.assertContains(response, "Last used", count=1)
                assert response.context["last_oauth_provider"] == "google"
                assert response.wsgi_request.user.is_anonymous
                assert LAST_OAUTH_PROVIDER_COOKIE not in response.cookies
                assert client.cookies[LAST_OAUTH_PROVIDER_COOKIE].value == "google"

    def test_missing_cookie_after_login_is_not_reconstructed(self):
        self.complete_login(self.client, self.google_token)
        self.client.get("/logout/")
        # Browsers omit cookies after expiry or clearing site data.
        self.client.cookies.pop(LAST_OAUTH_PROVIDER_COOKIE)

        response = self.client.get("/login/")

        self.assertNotContains(response, "Last used")
        assert response.context["last_oauth_provider"] is None
        assert LAST_OAUTH_PROVIDER_COOKIE not in response.cookies

    def test_same_account_has_independent_hints_in_two_browsers(self):
        first, second = Client(), Client()
        self.complete_login(first, self.google_token)
        self.complete_login(second, self.github_token)
        for client, provider in ((first, "google"), (second, "github")):
            client.get("/logout/")
            response = client.get("/login/")
            assert response.context["last_oauth_provider"] == provider
            self.assertContains(response, "Last used", count=1)

    def test_another_account_replaces_hint_in_shared_browser(self):
        self.complete_login(self.client, self.google_token)
        self.client.get("/logout/")
        another_user = User.objects.create_user(username="another-login-hint-user")
        self.github_token.coder = Coder.objects.create(user=another_user)
        self.github_token.save(update_fields=["coder"])

        self.complete_login(self.client, self.github_token)
        self.client.get("/logout/")
        response = self.client.get("/login/")

        assert response.context["last_oauth_provider"] == "github"
        self.assertContains(response, "Last used", count=1)


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
