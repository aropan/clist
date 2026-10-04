import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace

import jwt
import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone
from jwt.utils import base64url_encode
from oauth2_provider.models import AccessToken, Application, Grant
from oauth2_provider.views import RevokeTokenView, TokenView

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
