import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, patch

from django.contrib.auth.models import AnonymousUser, User
from django.db import connections
from django.db.models.query import QuerySet
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from my_oauth.models import Credential, Form, Service, Token
from my_oauth.views import form, login, process_data, query, refresh, response
from true_coders.models import Coder


class OAuthFormSetup:
    def setUp(self):
        self.service = Service.objects.create(
            name="form-provider",
            title="Form provider",
            user_id_field="id",
            code_uri="https://provider.example/authorize?state=%(state)s",
        )
        self.form = Form.objects.create(
            name="Test form", service=self.service, code="Account: {credential_login}", grant_credentials=True
        )
        self.token = Token.objects.create(service=self.service, user_id="form-user")

    def request(self, token=None, action=None):
        request = RequestFactory().get("/form/", {"action": action} if action else {})
        request.user = AnonymousUser()
        request.session = {}
        if token:
            request.session.update({
                "form_id": str(self.form.pk),
                "form_token_id": token.pk,
                "form_token_timestamp": timezone.now().timestamp(),
            })
        return request

    def credential(self, login="contest-account", **kwargs):
        return Credential.objects.create(form=self.form, login=login, password="test-only", **kwargs)

    def context(self, request, target=None):
        with patch("my_oauth.views.render", return_value=HttpResponse()) as render:
            result = form(request, (target or self.form).pk)
        assert result.status_code == 200
        return render.call_args.args[2]


class OAuthFormTest(OAuthFormSetup, TestCase):
    def test_expected_provider_login_grants_account(self):
        credential = self.credential()
        request = self.request(action="login")
        assert form(request, self.form.pk).status_code == 302
        request.GET = request.GET.copy()
        request.GET.clear()
        assert query(request, self.service.name).status_code == 302
        result = process_data(request, self.service, {}, {"id": "form-user", "email": "user@example.com"})
        assert result.url == reverse("auth:form", args=(self.form.pk,))
        context = self.context(request)
        assert context["code"] == "Account: contest-account"
        assert context["error"] is None
        credential.refresh_from_db()
        assert credential.token_id == self.token.pk
        assert credential.state == Credential.State.ASSIGNED

    def test_pending_form_login_rejects_another_provider_at_every_entry_point(self):
        self.credential()
        other = Service.objects.create(name="other-provider", user_id_field="id")
        request = self.request(action="login")
        form(request, self.form.pk)
        request.GET = request.GET.copy()
        request.GET.clear()
        assert query(request, self.service.name).status_code == 302
        state = request.session["state"]
        assert query(request, other.name).status_code == 400
        assert request.session["state"] == state
        with patch("my_oauth.views.requests.get") as get, patch("my_oauth.views.requests.post") as post:
            assert response(request, other.name).status_code == 400
        get.assert_not_called()
        post.assert_not_called()
        assert process_data(request, other, {}, {"id": "other", "email": "other@example.com"}).status_code == 400
        assert "form_token_id" not in request.session
        assert not Token.objects.filter(service=other).exists()
        assert not Credential.objects.filter(token__isnull=False).exists()

    def test_stored_token_from_another_provider_is_not_accepted(self):
        self.credential()
        other = Service.objects.create(name="other-provider", user_id_field="id")
        token = Token.objects.create(service=other, user_id="other")
        context = self.context(self.request(token))
        assert context["token"] is None
        assert context["code"] is None
        assert not Credential.objects.filter(token__isnull=False).exists()

    def test_form_login_cannot_be_reused_on_another_form(self):
        other = Form.objects.create(name="Other form", service=self.service, code="private form")
        context = self.context(self.request(self.token), target=other)
        assert context["token"] is None
        assert context["code"] is None

    def test_switching_forms_requires_new_authentication(self):
        other = Form.objects.create(name="Other form", service=self.service, code="private form")
        request = self.request(self.token, action="login")
        assert form(request, other.pk).status_code == 302
        assert request.session["form_id"] == str(other.pk)
        assert "form_token_id" not in request.session

    def test_expired_form_login_cannot_allocate_an_account(self):
        self.credential()
        request = self.request(self.token)
        request.session["form_token_timestamp"] = 1
        assert self.context(request)["token"] is None
        assert not Credential.objects.filter(token__isnull=False).exists()

    def test_exhausted_account_pool_renders_message(self):
        session = self.client.session
        session.update(self.request(self.token).session)
        session.save()
        result = self.client.get(reverse("auth:form", args=(self.form.pk,)))
        assert result.status_code == 200
        self.assertContains(result, "No accounts are currently available. Please try again later.")
        assert not Credential.objects.filter(token=self.token).exists()

    def test_assigned_account_is_reused_when_pool_is_empty(self):
        credential = self.credential(token=self.token, state=Credential.State.APPROVED)
        context = self.context(self.request(self.token))
        assert context["credential"] == credential
        assert context["error"] is None
        assert context["code"] == "Account: contest-account"

    def test_approved_account_without_token_is_not_reallocated(self):
        self.credential(state=Credential.State.APPROVED)
        assert self.context(self.request(self.token))["error"]
        assert not Credential.objects.filter(token__isnull=False).exists()

    def test_logout_does_not_allocate_an_account(self):
        self.credential()
        request = self.request(self.token, action="logout")
        assert form(request, self.form.pk).status_code == 302
        assert "form_token_id" not in request.session
        assert not Credential.objects.filter(token__isnull=False).exists()

    def test_normal_login_clears_pending_form_authentication(self):
        request = self.request(action="login")
        form(request, self.form.pk)
        with patch("my_oauth.views.render", return_value=HttpResponse()):
            login(request)
        for field in ("token_url", "token_id_field", "token_timestamp_field", "token_code_args", "token_service_id"):
            assert field not in request.session


class OAuthFormSettingsTest(OAuthFormSetup, TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="form-settings-owner")
        self.coder = Coder.objects.create(user=self.user)
        self.settings_url = reverse("coder:settings", kwargs={"tab": "social"})
        self.other = Service.objects.create(
            name="settings-provider", user_id_field="id", code_uri="https://settings.example/authorize?state=%(state)s"
        )
        self.form.service_code_args = '{"prompt": "consent"}'
        self.form.save(update_fields=["service_code_args"])

    def pending_form_request(self):
        request = self.request(action="login")
        request.user = self.user
        request.logger = Mock()
        form(request, self.form.pk)
        request.GET = RequestFactory().get("/").GET
        query(request, self.service.name)
        return request

    def assert_no_pending_form(self, request):
        for field in ("token_url", "token_id_field", "token_timestamp_field", "token_code_args", "token_service_id"):
            assert field not in request.session
        assert "form_token_id" not in request.session

    def test_settings_connect_starts_independent_login(self):
        for service in (self.service, self.other):
            with self.subTest(service=service.name):
                request = self.pending_form_request()
                old_state = request.session["state"]
                request.GET = RequestFactory().get("/", {"next": self.settings_url}).GET

                assert query(request, service.name).status_code == 302
                assert request.session["state"] != old_state
                self.assert_no_pending_form(request)
                assert request.session["next"] == self.settings_url

                result = process_data(request, service, {}, {"id": "settings-user", "email": "user@example.com"})
                assert result.url == reverse("auth:signup")
                token = Token.objects.get(pk=request.session["token_id"])
                assert token.service_id == service.pk
                self.assert_no_pending_form(request)

    def test_settings_refresh_saves_rotated_tokens_without_authenticating_form(self):
        for service in (self.service, self.other):
            with self.subTest(service=service.name):
                service.refresh_token_uri = "https://provider.example/refresh"
                service.refresh_token_post = '{"refresh_token": "%(refresh_token)s"}'
                service.data_uri = "https://provider.example/me"
                service.save(update_fields=["refresh_token_uri", "refresh_token_post", "data_uri"])
                token = Token.objects.create(
                    service=service,
                    coder=self.coder,
                    user_id="settings-user",
                    access_token={"access_token": "test-old-access", "refresh_token": "test-old-refresh"},
                )
                request = self.pending_form_request()
                new_tokens = {"access_token": "test-new-access", "refresh_token": "test-new-refresh"}
                profile = {"id": token.user_id, "email": "user@example.com"}
                with (
                    patch(
                        "my_oauth.utils.requests.post", return_value=Mock(status_code=200, text=json.dumps(new_tokens))
                    ) as post,
                    patch("my_oauth.views.requests.get", return_value=Mock(status_code=200, text=json.dumps(profile))),
                ):
                    result = refresh(request, service.name)

                assert result.status_code == 302
                assert result.url == self.settings_url
                post.assert_called_once()
                token.refresh_from_db()
                assert token.access_token == new_tokens
                self.assert_no_pending_form(request)
                assert "state" not in request.session

    def test_form_logout_cancels_pending_login(self):
        request = self.pending_form_request()
        request.GET = RequestFactory().get("/", {"action": "logout"}).GET
        assert form(request, self.form.pk).status_code == 302
        self.assert_no_pending_form(request)
        assert "state" not in request.session

        request.GET = RequestFactory().get("/").GET
        assert query(request, self.other.name).status_code == 302


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class OAuthFormConcurrencyTest(OAuthFormSetup, TransactionTestCase):
    def visit(self, token):
        try:
            return form(self.request(token), self.form.pk).content.decode()
        finally:
            connections.close_all()

    def run_concurrently(self, tokens):
        def render_code(request, template, context):
            return HttpResponse(context["code"] or "unavailable")

        with patch("my_oauth.views.render", side_effect=render_code), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.visit, token) for token in tokens]
            return [future.result(timeout=15) for future in futures]

    def synchronize_free_account_selection(self):
        barrier = Barrier(2)
        first = QuerySet.first

        def synchronized_first(queryset):
            result = first(queryset)
            if queryset.model is Credential and queryset.query.order_by == ("?",):
                barrier.wait(timeout=10)
            return result

        return patch.object(QuerySet, "first", synchronized_first)

    def test_two_identities_cannot_receive_the_same_last_account(self):
        credential = self.credential()
        other = Token.objects.create(service=self.service, user_id="other")
        with self.synchronize_free_account_selection():
            results = self.run_concurrently([self.token, other])
        assert sorted(results) == ["Account: contest-account", "unavailable"]
        credential.refresh_from_db()
        owner_index = results.index("Account: contest-account")
        assert credential.token_id == [self.token, other][owner_index].pk

    def test_two_identities_receive_distinct_available_accounts(self):
        self.credential(login="account-one")
        self.credential(login="account-two")
        other = Token.objects.create(service=self.service, user_id="other")
        with self.synchronize_free_account_selection():
            results = self.run_concurrently([self.token, other])
        assert sorted(results) == ["Account: account-one", "Account: account-two"]
        assert Credential.objects.filter(token__isnull=False).count() == 2

    def test_parallel_requests_for_one_identity_reuse_one_account(self):
        self.credential(login="account-one")
        self.credential(login="account-two")
        barrier = Barrier(2)
        get = QuerySet.get

        def synchronized_get(queryset, *args, **kwargs):
            if queryset.model is Token and queryset.query.select_for_update:
                barrier.wait(timeout=10)
            return get(queryset, *args, **kwargs)

        with patch.object(QuerySet, "get", synchronized_get):
            results = self.run_concurrently([self.token, self.token])
        assert results[0] == results[1]
        assert results[0] != "unavailable"
        assert Credential.objects.filter(token=self.token).count() == 1
        assert Credential.objects.filter(token__isnull=True).count() == 1
