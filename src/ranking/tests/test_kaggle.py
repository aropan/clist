from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from ranking.management.modules.kaggle import Statistic


class KaggleRequestTest(SimpleTestCase):
    @mock.patch(
        "ranking.management.modules.kaggle.get_headers",
        return_value={"User-Agent": "configured-user-agent", "Accept-Language": "en-US"},
    )
    @mock.patch("ranking.management.modules.kaggle.REQ.get", return_value={})
    def test_get_uses_curl_cookie_file_and_configured_headers(self, request_get, get_headers):
        headers = {"content-type": "application/json"}

        Statistic._get("https://www.kaggle.com/api/test", headers=headers, return_json=True)

        request_get.assert_called_once_with(
            "https://www.kaggle.com/api/test",
            headers={
                "User-Agent": "configured-user-agent",
                "Accept-Language": "en-US",
                "content-type": "application/json",
            },
            return_json=True,
            with_curl=True,
            curl_cookie_file=Statistic.CURL_COOKIE_FILE_,
        )
        get_headers.assert_called_once_with()

    @mock.patch("ranking.management.modules.kaggle.MozillaCookieJar")
    def test_get_xsrf_token_reads_curl_cookie_file(self, cookiejar_class):
        cookiejar = cookiejar_class.return_value
        cookiejar.__iter__.return_value = iter([
            SimpleNamespace(name="OTHER", value="ignored"),
            SimpleNamespace(name="XSRF-TOKEN", value="xsrf-token"),
        ])

        assert Statistic._get_xsrf_token() == "xsrf-token"
        cookiejar_class.assert_called_once_with(Statistic.CURL_COOKIE_FILE_)
        cookiejar.load.assert_called_once_with(ignore_discard=True, ignore_expires=True)
