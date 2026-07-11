import gzip
import io
import json
import os
import tempfile
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.test import SimpleTestCase
from lazy_load import lz

from ranking.management.modules import common
from ranking.management.modules.excepts import FailOnGetResponse
from ranking.tests.parser_regression import (
    discover_parser_fixtures,
    fixture_file_path,
    normalize_standings,
    use_parser_cache,
)
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
            fixture_path = Path(temporary_directory) / "1" / "2"
            (fixture_path / "httpcache").mkdir(parents=True)
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
