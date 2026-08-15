from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from pyclist.middleware import LocalhostCookieMiddleware

COOKIE_NAMES = (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME, "_skip_promotion_id")


@override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1", "dev.clist.by"])
class LocalhostCookieMiddlewareTest(SimpleTestCase):
    def setUp(self):
        self.request_factory = RequestFactory()
        self.middleware = LocalhostCookieMiddleware(self.get_response)

    @staticmethod
    def get_response(request):
        response = HttpResponse()
        for cookie_name in COOKIE_NAMES:
            response.set_cookie(cookie_name, "value", domain=".clist.by", secure=True)
        return response

    def test_localhost_cookies_are_host_only_and_work_over_http(self):
        for host in ("localhost:10042", "127.0.0.1:10042"):
            with self.subTest(host=host):
                response = self.middleware(self.request_factory.get("/", HTTP_HOST=host))

                for cookie_name in COOKIE_NAMES:
                    cookie = response.cookies[cookie_name]
                    assert cookie["domain"] == ""
                    assert not cookie["secure"]

    def test_dev_host_keeps_secure_domain_cookies(self):
        response = self.middleware(self.request_factory.get("/", HTTP_HOST="dev.clist.by"))

        for cookie_name in COOKIE_NAMES:
            cookie = response.cookies[cookie_name]
            assert cookie["domain"] == ".clist.by"
            assert cookie["secure"]
