import gzip
import io
import json
import os
import tempfile
import time
import urllib.error
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from lazy_load import lz

from clist.models import Contest, Resource
from ranking.management.modules import common
from ranking.management.modules.excepts import FailOnGetResponse
from ranking.models import Module
from ranking.tests.parser_regression import (
    assert_standings_equal,
    discover_parser_fixtures,
    fixture_file_path,
    get_standings,
    materialized_http_cache,
    normalize_standings,
    pack_http_cache,
    read_http_cache_archive,
    use_parser_cache,
    write_json,
)
from utils.ratelimiter import RateLimiter
from utils.requester import requester


class Response(io.BytesIO):
    def __init__(self, content, url, content_type="application/json", code=200):
        super().__init__(content)
        self.code = code
        self.url = url
        self.headers = {"Content-Type": content_type}

    def geturl(self):
        return self.url

    def info(self):
        return self.headers


class ParserRegressionHelpersTest(SimpleTestCase):
    def test_standings_mismatch_has_bounded_output(self):
        expected = {
            "result": {f"user_{index:04}": {"payload": "x" * 1000} for index in range(20)},
        }
        actual = {
            "result": {f"user_{index:04}": {"payload": "y" * 1000} for index in range(20)},
        }

        with pytest.raises(AssertionError) as error:
            assert_standings_equal(expected, actual, "parser regression mismatch for 1/2")

        message = str(error.value)
        assert "$.result.user_0000.payload: value differs" in message
        assert "$.result.user_0004.payload: value differs" in message
        assert "user_0005" not in message
        assert len(message) < 2500

    def test_write_json_creates_deterministic_gzip(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_path = root / "first.json.gz"
            second_path = root / "second.json.gz"

            write_json(first_path, {"result": {"alice": {"solving": 1}}})
            write_json(second_path, {"result": {"alice": {"solving": 1}}})

            first = first_path.read_bytes()
            assert first == second_path.read_bytes()
            assert first[:3] == b"\x1f\x8b\x08"
            assert first[3] & 0x08 == 0
            assert first[4:8] == b"\0\0\0\0"

    def test_http_cache_archive_is_deterministic_and_round_trips(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache_path = root / "httpcache"
            cache_path.mkdir()
            (cache_path / "page.html").write_bytes(b"public response")
            (cache_path / "page.html.meta.json").write_text('{"code": 200}\n')
            first_archive = root / "first-httpcache.json.gz"
            second_archive = root / "second-httpcache.json.gz"

            assert pack_http_cache(cache_path, first_archive) == 2
            assert pack_http_cache(cache_path, second_archive) == 2
            assert first_archive.read_bytes() == second_archive.read_bytes()
            assert read_http_cache_archive(first_archive) == {
                Path("page.html"): b"public response",
                Path("page.html.meta.json"): b'{"code": 200}\n',
            }

            fixture_path = root / "fixture"
            fixture_path.mkdir()
            first_archive.replace(fixture_path / "httpcache.json.gz")
            with materialized_http_cache(fixture_path) as materialized_cache:
                assert (materialized_cache / "page.html").read_bytes() == b"public response"
                assert (materialized_cache / "page.html.meta.json").read_text() == '{"code": 200}\n'

    def test_http_cache_archive_normalizes_inner_gzip(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache_path = root / "httpcache"
            cache_path.mkdir()
            with gzip.open(cache_path / "page.html.gz", "wb") as output_file:
                output_file.write(b"compressed response")

            archive_path = root / "httpcache.json.gz"
            pack_http_cache(cache_path, archive_path)

            assert read_http_cache_archive(archive_path) == {Path("page.html"): b"compressed response"}

    def test_http_cache_archive_rejects_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_path = Path(temporary_directory) / "httpcache.json.gz"
            write_json(archive_path, {"files": {"../secret": ""}, "version": 1})

            with pytest.raises(ValueError, match="invalid HTTP cache archive path"):
                read_http_cache_archive(archive_path)

    def test_normalize_standings_filters_volatile_fields(self):
        standings = {
            "result": {
                "tourist": {
                    "member": "tourist",
                    "parsed_time": "volatile",
                    "profile_url": "https://example.com/tourist?token=secret",
                    "solving": 1,
                }
            },
            "problems": [{"short": "A", "url": "https://example.com/problem/A"}],
            "options": {"medals": [{"name": "gold", "count": 1}], "timeline": {"attempt_penalty": 600}},
            "hidden_fields": ["parsed_time"],
        }

        assert normalize_standings(standings) == {
            "options": {"medals": [{"count": 1, "name": "gold"}]},
            "problems": [{"short": "A"}],
            "result": {"tourist": {"member": "tourist", "solving": 1}},
        }
        assert normalize_standings({"result": {}, "options": None}) == {"result": {}}

    def test_requester_replays_json_with_metadata(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            req = requester(proxy=False, cookie_filename=None, caching=True)
            req.cookie_filename = None
            req.dir_cache = f"{temporary_directory}{os.sep}"
            req.cache_timeout = 2**31 - 1
            req.limit_file_cache = 0
            req.time_sleep = 0

            url = "https://example.com/api/standings"
            req.opener.open = Mock(return_value=Response(b'{"result": {"ok": true}}', url))
            assert req.get(url, return_json=True) == {"result": {"ok": True}}
            req.opener.open.assert_called_once()

            req.opener.open = Mock(side_effect=AssertionError("network should not be used"))
            assert req.get(url, return_json=True, return_url=True, return_code=True) == [
                {"result": {"ok": True}},
                url,
                200,
            ]
            req.opener.open.assert_not_called()
            assert req.get(url, return_last_url=True) == url
            req.opener.open.assert_not_called()
            assert req.response.info()["Content-Type"] == "application/json"
            assert req.response.getheaders() == [("Content-Type", "application/json")]

            cache_files = list(Path(temporary_directory).glob("*.html"))
            assert len(cache_files) == 1
            assert json.loads(cache_files[0].read_text()) == {"result": {"ok": True}}
            assert Path(f"{cache_files[0]}.meta.json").is_file()

    def test_requester_can_refresh_cached_response(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            req = requester(proxy=False, cookie_filename=None, caching=True)
            req.cookie_filename = None
            req.dir_cache = f"{temporary_directory}{os.sep}"
            req.cache_timeout = 2**31 - 1
            req.limit_file_cache = 0
            req.time_sleep = 0

            url = "https://example.com/private"
            req.opener.open = Mock(return_value=Response(b"session expired", url))
            assert req.get(url) == "session expired"

            req.opener.open = Mock(return_value=Response(b"authenticated", url))
            assert req.get(url, refresh_cache=True) == "authenticated"
            req.opener.open.assert_called_once()

            req.opener.open = Mock(side_effect=AssertionError("network should not be used"))
            assert req.get(url) == "authenticated"
            req.opener.open.assert_not_called()

    def test_parser_cache_replays_curl_url_with_cache_busting_parameter(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            live_url = "https://example.com/api/standings?page=1&_=1000"
            replay_url = "https://example.com/api/standings?page=1&_=2000"
            response = Response(b'{"result": {"ok": true}}', live_url)

            with (
                patch("utils.requester.curl_response", return_value=response) as curl_response,
                use_parser_cache(common, temporary_directory, allow_network=True),
            ):
                assert common.REQ.get(live_url, return_json=True, with_curl=True) == {"result": {"ok": True}}

            curl_response.assert_called_once()

            with use_parser_cache(common, temporary_directory, allow_network=False):
                assert common.REQ.get(replay_url, return_json=True, with_curl=True) == {"result": {"ok": True}}

    def test_parser_cache_replays_post_request(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            url = "https://example.com/graphql"
            post = b'{"query": "query standings { rows { rank } }"}'
            response = Response(b'{"data": {"rows": []}}', url)

            with (
                patch("utils.requester.curl_response", return_value=response) as curl_response,
                use_parser_cache(common, temporary_directory, allow_network=True),
            ):
                assert common.REQ.get(url, post=post, return_json=True, with_curl=True) == {"data": {"rows": []}}

            curl_response.assert_called_once()

            with use_parser_cache(common, temporary_directory, allow_network=False):
                assert common.REQ.get(url, post=post, return_json=True, with_curl=True) == {"data": {"rows": []}}

    def test_requester_replays_gzipped_cache_file(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            req = requester(proxy=False, cookie_filename=None, caching=True)
            req.cookie_filename = None
            req.dir_cache = f"{temporary_directory}{os.sep}"
            req.cache_timeout = 2**31 - 1
            req.limit_file_cache = 0
            req.time_sleep = 0

            url = "https://example.com/api/standings"
            req.opener.open = Mock(return_value=Response(b'{"result": {"ok": true}}', url))
            assert req.get(url, return_json=True) == {"result": {"ok": True}}

            cache_file = next(Path(temporary_directory).glob("*.html"))
            gzip_cache_file = cache_file.with_suffix(f"{cache_file.suffix}.gz")
            with cache_file.open("rb") as input_file, gzip.open(gzip_cache_file, "wb") as output_file:
                output_file.write(input_file.read())
            cache_file.unlink()

            req.opener.open = Mock(side_effect=AssertionError("network should not be used"))
            assert req.get(url, return_json=True) == {"result": {"ok": True}}
            req.opener.open.assert_not_called()

    def test_discover_parser_fixtures_accepts_gzipped_expected_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture_path = root / "1" / "2"
            fixture_path.mkdir(parents=True)
            cache_path = root / "recording-cache"
            cache_path.mkdir(parents=True)
            (cache_path / "page.html").write_text("cached response")
            pack_http_cache(cache_path, fixture_path / "httpcache.json.gz")
            (fixture_path / "db.json").write_text("{}")
            with gzip.open(fixture_path / "expected_standings.json.gz", "wt") as output_file:
                json.dump({}, output_file)

            assert discover_parser_fixtures(Path(temporary_directory)) == [fixture_path]
            assert fixture_file_path(fixture_path, "expected_standings.json") == (
                fixture_path / "expected_standings.json.gz"
            )

    def test_requester_replays_non_utf8_binary_cache(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            req = requester(proxy=False, cookie_filename=None, caching=True)
            req.cookie_filename = None
            req.dir_cache = f"{temporary_directory}{os.sep}"
            req.cache_timeout = 2**31 - 1
            req.limit_file_cache = 0
            req.time_sleep = 0

            url = "https://example.com/image.png"
            content = b"\x89PNG\r\n\x1a\n\xff\x00"
            req.opener.open = Mock(return_value=Response(content, url, content_type="image/png"))
            assert req.get(url) == content
            req.opener.open.assert_called_once()

            cache_files = list(Path(temporary_directory).glob("*.html"))
            assert len(cache_files) == 1
            metadata = json.loads(Path(f"{cache_files[0]}.meta.json").read_text())
            assert metadata["encoding"] == "base64"

            req.opener.open = Mock(side_effect=AssertionError("network should not be used"))
            assert req.get(url) == content
            req.opener.open.assert_not_called()

    def test_requester_replays_http_error(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            req = requester(proxy=False, cookie_filename=None, caching=True)
            req.cookie_filename = None
            req.dir_cache = f"{temporary_directory}{os.sep}"
            req.cache_timeout = 2**31 - 1
            req.cache_errors = True
            req.limit_file_cache = 0
            req.time_sleep = 0

            url = "https://example.com/api/unavailable"
            error = urllib.error.HTTPError(
                url,
                400,
                "Bad Request",
                {"Content-Type": "application/json"},
                io.BytesIO(b'{"status": "FAILED"}'),
            )
            req.opener.open = Mock(side_effect=error)
            with pytest.raises(FailOnGetResponse) as recorded:
                req.get(url, return_json=True, raise_codes={400})
            assert json.loads(recorded.value.response) == {"status": "FAILED"}

            req.opener.open = Mock(side_effect=AssertionError("network should not be used"))
            with pytest.raises(FailOnGetResponse) as replayed:
                req.get(url, return_json=True)
            assert json.loads(replayed.value.response) == {"status": "FAILED"}
            req.opener.open.assert_not_called()

    def test_requester_does_not_cache_http_error_by_default(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            req = requester(proxy=False, cookie_filename=None, caching=True)
            req.cookie_filename = None
            req.dir_cache = f"{temporary_directory}{os.sep}"
            req.cache_timeout = 2**31 - 1
            req.limit_file_cache = 0
            req.time_sleep = 0

            url = "https://example.com/api/transient"
            error = urllib.error.HTTPError(
                url,
                500,
                "Server Error",
                {"Content-Type": "application/json"},
                io.BytesIO(b'{"status": "FAILED"}'),
            )
            req.opener.open = Mock(side_effect=error)
            with pytest.raises(FailOnGetResponse):
                req.get(url, return_json=True)

            req.opener.open = Mock(return_value=Response(b'{"status": "OK"}', url))
            assert req.get(url, return_json=True) == {"status": "OK"}
            req.opener.open.assert_called_once()

    def test_requester_preserves_non_json_sentinel(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            req = requester(proxy=False, cookie_filename=None, caching=True)
            req.cookie_filename = None
            req.dir_cache = f"{temporary_directory}{os.sep}"
            req.cache_timeout = 2**31 - 1
            req.limit_file_cache = 0
            req.time_sleep = 0

            url = "https://example.com/text"
            req.opener.open = Mock(return_value=Response(b"123", url, content_type="text/plain"))
            expected = {"page": "123", "__no_json": True}
            assert req.get(url, return_json=True) == expected

            req.opener.open = Mock(side_effect=AssertionError("network should not be used"))
            assert req.get(url, return_json=True) == expected
            req.opener.open.assert_not_called()

    def test_lazy_load_requester_uses_fixture_cache(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            req = requester(proxy=False, cookie_filename=None, caching=False)
            req.cookie_filename = None
            original_dir_cache = req.dir_cache
            plugin_module = SimpleNamespace(custom_requester=lz(lambda: req))

            with use_parser_cache(plugin_module, temporary_directory, allow_network=False):
                assert req.caching is True
                assert req.cache_errors is True
                assert req.dir_cache == f"{Path(temporary_directory).resolve()}{os.sep}"

            assert req.caching is False
            assert req.cache_errors is False
            assert req.dir_cache == original_dir_cache

    def test_offline_guard_rejects_cache_miss(self):
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            use_parser_cache(common, temporary_directory, allow_network=False),
            pytest.raises(AssertionError, match="unexpected network access"),
        ):
            common.REQ.get("https://example.com/missing")

    def test_offline_parser_cache_bypasses_rate_limiter(self):
        rate_limiter = RateLimiter(max_calls=1, period=3600)

        @rate_limiter
        def limited_call():
            return "result"

        assert limited_call() == "result"
        recorded_calls = list(rate_limiter.calls)

        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch("utils.ratelimiter.time.sleep") as sleep,
            use_parser_cache(common, temporary_directory, allow_network=False),
        ):
            assert limited_call() == "result"

        sleep.assert_not_called()
        assert list(rate_limiter.calls) == recorded_calls

    def test_network_parser_cache_preserves_rate_limiter(self):
        rate_limiter = RateLimiter(max_calls=1, period=3600)

        @rate_limiter
        def limited_call():
            return "result"

        assert limited_call() == "result"

        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch("utils.ratelimiter.time.sleep") as sleep,
            use_parser_cache(common, temporary_directory, allow_network=True),
        ):
            assert limited_call() == "result"

        sleep.assert_called_once()

    def test_offline_parser_cache_bypasses_direct_sleep(self):
        def direct_sleep(_seconds):
            raise AssertionError("plugin sleep should be bypassed")

        plugin_module = SimpleNamespace(sleep=direct_sleep, time=time)
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.object(time, "sleep", side_effect=AssertionError("time.sleep should be bypassed")) as sleep,
            use_parser_cache(plugin_module, temporary_directory, allow_network=False),
        ):
            plugin_module.sleep(2)
            plugin_module.time.sleep(2)

        sleep.assert_not_called()
        assert plugin_module.sleep is direct_sleep


class ParserRegressionIsolationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        current_time = timezone.now()
        resource = Resource.objects.create(
            host="parser-isolation.example.com",
            enable=True,
            url="https://parser-isolation.example.com/",
            color="#336699",
            icon_file="resources/test.png",
            icon_updated_at=current_time,
        )
        Module.objects.create(
            resource=resource,
            path="ranking.management.modules.common",
            long_contest_idle=timedelta(hours=6),
            shortly_after=timedelta(minutes=30),
            delay_shortly_after=timedelta(minutes=5),
            max_delay_after_end=timedelta(hours=1),
            delay_on_error=timedelta(hours=1),
        )
        cls.contest = Contest.objects.create(
            resource=resource,
            title="Parser isolation",
            start_time=current_time - timedelta(hours=2),
            end_time=current_time - timedelta(hours=1),
            duration_in_secs=3600,
            url="https://parser-isolation.example.com/contest",
            key="parser-isolation",
            host=resource.host,
            parsed_time=current_time,
            info={"state": {"value": 1}},
            submissions_info={"cursor": 2},
        )

    def test_get_standings_loads_isolated_contest(self):
        class MutatingStatistic:
            def __init__(self, contest):
                self.contest = contest

            def get_standings(self, **kwargs):
                state = self.contest.info.pop("state")
                cursor = self.contest.submissions_info.pop("cursor")
                return {"result": {"test": {"member": "test", "state": state, "cursor": cursor}}}

        original_info = deepcopy(self.contest.info)
        original_submissions_info = deepcopy(self.contest.submissions_info)

        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.object(common, "Statistic", MutatingStatistic, create=True),
        ):
            first = get_standings(self.contest, temporary_directory, allow_network=False)
            second = get_standings(self.contest, temporary_directory, allow_network=False)

        assert first == second
        assert self.contest.info == original_info
        assert self.contest.submissions_info == original_submissions_info
