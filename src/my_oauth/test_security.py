import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

import jwt
import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone
from jwt.utils import base64url_encode
from oauth2_provider.models import AccessToken, Application, Grant, get_device_grant_model
from oauth2_provider.oauth2_validators import OAuth2Validator
from oauth2_provider.views import RevokeTokenView, TokenView
from oauth2_provider.views.device import DeviceAuthorizationView
from oauthlib.oauth2 import Server

from clist.api.authentication import OAuth2ScopedAuthentication
from my_oauth.models import Service
from my_oauth.utils import access_token_from_response


class SignedOAuthResponseTest(SimpleTestCase):
    def setUp(self):
        self.service = Service(
            app_id="test-client",
            secret="test-secret-with-at-least-32-bytes",
            signed_field="id_token",
            signed_method="HS256",
        )
        self.claims = {
            "sub": "provider-user",
            "aud": self.service.app_id,
            "exp": int((timezone.now() + timedelta(minutes=5)).timestamp()),
        }

    def decode(self, token):
        response = SimpleNamespace(status_code=200, text=json.dumps({"id_token": token, "access_token": "opaque"}))
        return access_token_from_response(self.service, response)

    def encode(self, **claims):
        return jwt.encode({**self.claims, **claims}, self.service.secret, algorithm="HS256")

    def test_valid_signed_response_preserves_access_token(self):
        assert self.decode(self.encode()) == {**self.claims, "access_token": "opaque"}

    def test_invalid_signature_expiry_and_audience_are_rejected(self):
        tokens = (
            (jwt.encode(self.claims, "another-secret-with-at-least-32-bytes", algorithm="HS256"), "Error decoding"),
            (self.encode(exp=0), "Signature has expired"),
            (self.encode(aud="other-client"), "Invalid audience"),
        )
        for token, error in tokens:
            with self.subTest(error=error), pytest.raises(Exception, match=error):
                self.decode(token)

    def test_noncanonical_signature_is_rejected(self):
        with pytest.raises(Exception, match="Error decoding signature"):
            self.decode(self.encode() + "!!!!")

    def test_decode_does_not_change_service_verification_options(self):
        options = {"verify_signature": False}
        self.service.signed_args = {"options": options}
        token = self.encode(exp=0)
        self.decode(token)

        assert options == {"verify_signature": False}
        options["verify_signature"] = True
        with pytest.raises(Exception, match="Signature has expired"):
            self.decode(token)

    def test_unexpected_signing_algorithm_is_rejected(self):
        token = jwt.encode(self.claims, self.service.secret, algorithm="HS384")
        with pytest.raises(jwt.InvalidAlgorithmError):
            self.decode(token)


class OAuthProviderCompatibilityTest(TestCase):
    def authenticate(self, token, scope="read"):
        request = RequestFactory().get("/api/v4/contest/", HTTP_AUTHORIZATION=f"Bearer {token}")
        request.user = AnonymousUser()
        return OAuth2ScopedAuthentication(get=scope).is_authenticated(request), request.user

    def test_pkce_exchange_refresh_and_revocation(self):
        user = User.objects.create_user(username="oauth-security-test")
        client_secret = "oauth-client-secret-for-tests"
        redirect_uri = "https://client.example/callback"
        application = Application.objects.create(
            user=user,
            client_secret=client_secret,
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris=redirect_uri,
        )
        verifier = "v" * 64
        Grant.objects.create(
            user=user,
            application=application,
            code="test-authorization-code",
            expires=timezone.now() + timedelta(minutes=5),
            redirect_uri=redirect_uri,
            scope="read",
            code_challenge=base64url_encode(hashlib.sha256(verifier.encode()).digest()).decode(),
            code_challenge_method="S256",
        )

        def post(view, path, **data):
            request = RequestFactory().post(
                path, {"client_id": application.client_id, "client_secret": client_secret, **data}
            )
            request.user = AnonymousUser()
            return view.as_view()(request)

        exchange = {
            "grant_type": "authorization_code",
            "code": "test-authorization-code",
            "redirect_uri": redirect_uri,
        }
        response = post(TokenView, "/o/token/", **exchange, code_verifier="wrong-verifier")
        assert response.status_code == 400
        assert json.loads(response.content)["error"] == "invalid_grant"

        response = post(TokenView, "/o/token/", **exchange, code_verifier=verifier)
        assert response.status_code == 200
        tokens = json.loads(response.content)
        authenticated, token_user = self.authenticate(tokens["access_token"])
        assert authenticated
        assert token_user.pk == user.pk
        assert self.authenticate(tokens["access_token"], scope="write")[0] is False

        response = post(TokenView, "/o/token/", grant_type="refresh_token", refresh_token=tokens["refresh_token"])
        assert response.status_code == 200
        token = json.loads(response.content)["access_token"]
        assert self.authenticate(token)[0]

        response = post(RevokeTokenView, "/o/revoke_token/", token=token, callback="untrustedCallback")
        assert response.status_code == 200
        assert self.authenticate(token)[0] is False
        assert b"untrustedCallback" not in response.content

    def test_existing_plaintext_tokens_remain_supported(self):
        user = User.objects.create_user(username="existing-api-user")
        token = AccessToken.objects.create(
            user=user,
            token="existing-opaque-token",
            expires=timezone.now() + timedelta(minutes=5),
            scope="read",
        )
        authenticated, token_user = self.authenticate(token.token)
        assert authenticated
        assert token_user.pk == user.pk


class DeviceFlowCompatibilityTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="device-oauth-security-test")
        self.application = Application.objects.create(
            user=self.user,
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_DEVICE_CODE,
        )
        self.device_grant_model = get_device_grant_model()

    def create_grant(self, **kwargs):
        return self.device_grant_model.objects.create(**{
            "client_id": self.application.client_id,
            "device_code": "device-code-for-tests",
            "user_code": "user-code-for-tests",
            "user": self.user,
            "scope": "read",
            "status": self.device_grant_model.AUTHORIZED,
            "expires": timezone.now() + timedelta(minutes=5),
            **kwargs,
        })

    def token_response(self, **params):
        server = Server(OAuth2Validator())
        body = urlencode({
            "client_id": self.application.client_id,
            "grant_type": Application.GRANT_DEVICE_CODE,
            **params,
        })
        _headers, body, status = server.create_token_response(
            "https://example.com/o/token/", http_method="POST", body=body
        )
        return status, json.loads(body)

    def device_authorization_response(self, params, query=()):
        path = "/o/device-authorization/"
        if query:
            path += "?" + urlencode(query)
        request = RequestFactory().post(path, urlencode(params), content_type="application/x-www-form-urlencoded")
        request.user = AnonymousUser()
        return DeviceAuthorizationView.as_view()(request)

    def test_device_authorization_accepts_omitted_or_empty_scope(self):
        for params, query in (([], []), ([("scope", "")], []), ([], [("scope", "")])):
            with self.subTest(params=params, query=query):
                response = self.device_authorization_response(
                    [("client_id", self.application.client_id), *params], query
                )

                assert response.status_code == 200, response.content
                body = json.loads(response.content)
                grant = self.device_grant_model.objects.get(device_code=body["device_code"])
                assert grant.scope == "read"

    def test_device_authorization_rejects_duplicate_parameters(self):
        cases = (
            ([("scope", ""), ("scope", "")], []),
            ([("scope", "read"), ("scope", "")], []),
            ([("scope", ""), ("scope", "read")], []),
            ([("scope", "read"), ("scope", "write")], []),
            ([("client_id", self.application.client_id)], []),
            ([("client_id", "another-client")], []),
            ([("scope", "")], [("scope", "read")]),
            ([("scope", "read")], [("scope", "")]),
            ([], [("scope", "read"), ("scope", "")]),
            ([], [("client_id", self.application.client_id)]),
        )
        for params, query in cases:
            with self.subTest(params=params, query=query):
                grant_count = self.device_grant_model.objects.count()
                response = self.device_authorization_response(
                    [("client_id", self.application.client_id), *params], query
                )

                assert response.status_code == 400
                assert json.loads(response.content)["error"] == "invalid_request"
                assert self.device_grant_model.objects.count() == grant_count

    def test_device_authorization_rejects_invalid_scope(self):
        for scope in ("unknown-scope", " "):
            with self.subTest(scope=scope):
                response = self.device_authorization_response([
                    ("client_id", self.application.client_id),
                    ("scope", scope),
                ])

                assert response.status_code == 400
                assert json.loads(response.content)["error"] == "invalid_scope"
                assert not self.device_grant_model.objects.exists()

    def test_missing_or_unknown_device_code_is_rejected(self):
        for params, error in (
            ({}, "invalid_request"),
            ({"device_code": ""}, "invalid_request"),
            ({"device_code": "unknown-device-code"}, "invalid_grant"),
        ):
            with self.subTest(params=params):
                status, body = self.token_response(**params)

                assert status == 400
                assert body["error"] == error
                assert not AccessToken.objects.filter(application=self.application).exists()

    def test_device_code_from_another_client_is_rejected(self):
        grant = self.create_grant(client_id="another-client")

        status, body = self.token_response(device_code=grant.device_code)

        assert status == 400
        assert body["error"] == "invalid_grant"
        assert not AccessToken.objects.filter(application=self.application).exists()

    def test_unauthorized_or_expired_device_code_is_rejected(self):
        for grant_status, expired, error in (
            (self.device_grant_model.AUTHORIZATION_PENDING, False, "authorization_pending"),
            (self.device_grant_model.DENIED, False, "access_denied"),
            (self.device_grant_model.AUTHORIZED, True, "expired_token"),
        ):
            with self.subTest(status=grant_status):
                expires = timezone.now() + timedelta(minutes=-5 if expired else 5)
                grant = self.create_grant(device_code=grant_status, status=grant_status, expires=expires)

                status, body = self.token_response(device_code=grant.device_code)

                assert status == 400
                assert body["error"] == error
                assert not AccessToken.objects.filter(application=self.application).exists()

    def test_device_authorization_and_exchange_preserve_approved_scopes(self):
        request = RequestFactory().post(
            "/o/device_authorization/",
            urlencode({"client_id": self.application.client_id, "scope": "read"}),
            content_type="application/x-www-form-urlencoded",
        )
        request.user = AnonymousUser()

        response = DeviceAuthorizationView.as_view()(request)

        assert response.status_code == 200, response.content
        body = json.loads(response.content)
        assert "scope" not in body
        grant = self.device_grant_model.objects.get(device_code=body["device_code"])
        assert grant.scope == "read"
        grant.user = self.user
        grant.status = self.device_grant_model.AUTHORIZED
        grant.save(update_fields=["user", "status"])
        request = RequestFactory().post(
            "/o/token/",
            urlencode({
                "client_id": self.application.client_id,
                "grant_type": Application.GRANT_DEVICE_CODE,
                "device_code": grant.device_code,
                "scope": "write",
            }),
            content_type="application/x-www-form-urlencoded",
        )
        request.user = AnonymousUser()

        response = TokenView.as_view()(request)

        assert response.status_code == 200
        body = json.loads(response.content)
        assert body["scope"] == "read"
        token = AccessToken.objects.get(application=self.application)
        assert token.user_id == self.user.pk
        assert token.scope == "read"
