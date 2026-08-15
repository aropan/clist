import gzip
import json
import os
import time
import urllib.request
from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from hashlib import sha256
from io import BytesIO, TextIOWrapper
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import NamedTuple
from unittest.mock import patch
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests
from django.core.management import call_command
from django.db.models import F
from django.test import TestCase
from lazy_object_proxy import Proxy as LazyProxy

from clist.models import Contest
from ranking.management.modules.common import REQ
from ranking.management.modules.excepts import FailOnGetResponse
from utils.lazy import LazyObject
from utils.ratelimiter import RateLimiter
from utils.requester import requester

PARSER_FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "parsers"
FIXTURE_FILENAMES = ("db.json", "expected_standings.json", "httpcache.json")
HTTP_CACHE_ARCHIVE_VERSION = 1
HTTP_CACHE_FILENAME = "httpcache.json.gz"

SNAPSHOT_FIELDS = ("result", "problems")
IGNORED_FIELDS = {
    "_time",
    "access_token",
    "apiSig",
    "api_signature",
    "parsed_time",
    "refresh_token",
    "signature",
    "standings_url",
    "token",
    "url",
}
IGNORED_FIELD_SUFFIXES = ("_signature", "_timestamp", "_token", "_url")

REQUESTER_ATTRIBUTES = {
    "cache_errors": True,
    "cache_timeout": 2**31 - 1,
    "caching": True,
    "counter_file_cache": 1,
    "debug_output": False,
    "last_page": None,
    "last_url": None,
    "limit_file_cache": 0,
    "ref_url": None,
    "time_sleep": 0,
}


class StandingsContext(NamedTuple):
    users: list[str] | None
    statistics: dict | None


def fixture_component(value):
    return quote(str(value), safe="._-")


def fixture_resource_component(host):
    component = quote(str(host), safe=".-").replace("_", "%5F")
    return component.replace("%2F", "__")


def parser_fixture_path(resource_host, contest_id, root=PARSER_FIXTURES_ROOT):
    return Path(root) / fixture_resource_component(resource_host) / fixture_component(contest_id)


def fixture_path_for_contest(contest):
    return parser_fixture_path(contest.resource.host, contest.pk)


def discover_parser_fixtures(root=PARSER_FIXTURES_ROOT):
    if not root.exists():
        return []
    fixtures = []
    for db_path in root.rglob("db.json"):
        fixture_path = db_path.parent
        if all(fixture_file_path(fixture_path, filename).is_file() for filename in FIXTURE_FILENAMES):
            fixtures.append(fixture_path)
    return sorted(fixtures, key=lambda path: path.relative_to(root).as_posix())


def fixture_file_path(fixture_path, filename):
    path = Path(fixture_path) / filename
    if path.is_file():
        return path
    return path.with_suffix(f"{path.suffix}.gz")


def read_json(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as input_file:
        return json.load(input_file)


def _normalize_value(value):
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            key = str(key)
            if key in IGNORED_FIELDS or key.endswith(IGNORED_FIELD_SUFFIXES):
                continue
            normalized[key] = _normalize_value(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    if isinstance(value, set):
        normalized = [_normalize_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    return value


def normalize_standings(standings):
    snapshot = {field: standings[field] for field in SNAPSHOT_FIELDS if field in standings}
    medals = (standings.get("options") or {}).get("medals")
    if medals is not None:
        snapshot["options"] = {"medals": medals}
    normalized = _normalize_value(snapshot)
    return json.loads(json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str))


def _diff_path(path, key):
    if isinstance(key, str) and key.isidentifier():
        return f"{path}.{key}"
    return f"{path}[{key!r}]"


def _diff_value(value, limit=160):
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(rendered) > limit:
        return f"{rendered[:limit]}..."
    return rendered


def standings_diff_lines(expected, actual, limit=5):
    lines = []

    def add(message):
        if len(lines) < limit:
            lines.append(message)

    def compare(expected_value, actual_value, path):
        if len(lines) >= limit:
            return
        if type(expected_value) is not type(actual_value):
            add(
                f"{path}: type differs; expected={type(expected_value).__name__} "
                f"{_diff_value(expected_value)}, actual={type(actual_value).__name__} {_diff_value(actual_value)}"
            )
            return
        if isinstance(expected_value, dict):
            expected_keys = set(expected_value)
            actual_keys = set(actual_value)
            for key in sorted(expected_keys - actual_keys, key=str):
                add(f"{_diff_path(path, key)}: missing in actual; expected={_diff_value(expected_value[key])}")
            for key in sorted(actual_keys - expected_keys, key=str):
                add(f"{_diff_path(path, key)}: unexpected in actual; actual={_diff_value(actual_value[key])}")
            for key in sorted(expected_keys & actual_keys, key=str):
                compare(expected_value[key], actual_value[key], _diff_path(path, key))
            return
        if isinstance(expected_value, list):
            if len(expected_value) != len(actual_value):
                add(f"{path}: length differs; expected={len(expected_value)}, actual={len(actual_value)}")
            for index, (expected_item, actual_item) in enumerate(zip(expected_value, actual_value)):
                compare(expected_item, actual_item, f"{path}[{index}]")
            return
        if expected_value != actual_value:
            add(f"{path}: value differs; expected={_diff_value(expected_value)}, actual={_diff_value(actual_value)}")

    compare(expected, actual, "$")
    return lines


def assert_standings_equal(expected, actual, message, diff_limit=5):
    if expected == actual:
        return
    differences = standings_diff_lines(expected, actual, limit=diff_limit)
    detail = "\n".join(f"- {line}" for line in differences) or "- difference details unavailable"
    raise AssertionError(f"{message}\nDifferences (up to {diff_limit}):\n{detail}")


@contextmanager
def open_deterministic_gzip(path, mode="wb", compresslevel=9):
    if mode not in {"wb", "wt"}:
        raise ValueError(f"unsupported gzip mode: {mode}")
    with (
        Path(path).open("wb") as raw_output,
        gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=compresslevel,
            fileobj=raw_output,
            mtime=0,
        ) as gzip_output,
    ):
        if mode == "wb":
            yield gzip_output
        else:
            with TextIOWrapper(gzip_output, encoding="utf-8", newline="\n") as text_output:
                yield text_output


def write_json(path, data):
    path = Path(path)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")

    def write(output):
        json.dump(data, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")

    if path.suffix == ".gz":
        with open_deterministic_gzip(temporary_path, "wt") as output:
            write(output)
    else:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as output:
            write(output)
    temporary_path.replace(path)


def write_expected_standings(path, standings, compressed=False):
    filename = "expected_standings.json.gz" if compressed else "expected_standings.json"
    write_json(Path(path) / filename, normalize_standings(standings))


def _http_cache_archive_name(name):
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError(f"invalid HTTP cache archive path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"invalid HTTP cache archive path: {name!r}")
    return path


def read_http_cache_archive(path):
    path = Path(path)
    try:
        archive = read_json(path)
    except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError) as error:
        raise ValueError(f"invalid HTTP cache archive: {path}") from error
    if not isinstance(archive, dict) or archive.get("version") != HTTP_CACHE_ARCHIVE_VERSION:
        raise ValueError(f"unsupported HTTP cache archive format: {path}")
    files = archive.get("files")
    if not isinstance(files, dict):
        raise ValueError(f"invalid HTTP cache archive files: {path}")

    decoded = {}
    for name, content in sorted(files.items()):
        archive_path = _http_cache_archive_name(name)
        if not isinstance(content, str):
            raise ValueError(f"invalid HTTP cache archive content for {name!r}: {path}")
        try:
            decoded[archive_path] = b64decode(content, validate=True)
        except (Base64Error, ValueError) as error:
            raise ValueError(f"invalid HTTP cache archive content for {name!r}: {path}") from error
    return decoded


def pack_http_cache(cache_path, archive_path):
    cache_path = Path(cache_path)
    files = {}
    for path in sorted(cache_path.rglob("*")):
        if not path.is_file():
            continue
        relative_path = PurePosixPath(path.relative_to(cache_path).as_posix())
        content = path.read_bytes()
        if relative_path.suffix == ".gz":
            try:
                content = gzip.decompress(content)
            except OSError as error:
                raise ValueError(f"invalid gzip HTTP cache file: {path}") from error
            relative_path = relative_path.with_suffix("")
        name = _http_cache_archive_name(relative_path.as_posix()).as_posix()
        if name in files:
            raise ValueError(f"duplicate HTTP cache archive path: {name}")
        files[name] = b64encode(content).decode("ascii")

    write_json(
        archive_path,
        {
            "files": files,
            "version": HTTP_CACHE_ARCHIVE_VERSION,
        },
    )
    return len(files)


def unpack_http_cache(archive_path, cache_path):
    cache_path = Path(cache_path)
    cache_path.mkdir(parents=True, exist_ok=True)
    for relative_path, content in read_http_cache_archive(archive_path).items():
        path = cache_path.joinpath(*relative_path.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


@contextmanager
def materialized_http_cache(fixture_path):
    archive_path = fixture_file_path(fixture_path, "httpcache.json")
    if not archive_path.is_file():
        raise FileNotFoundError(f"missing HTTP cache archive: {archive_path}")
    with TemporaryDirectory(prefix="clist-parser-httpcache-") as temporary_directory:
        cache_path = Path(temporary_directory)
        unpack_http_cache(archive_path, cache_path)
        yield cache_path


def _request_url(request):
    url = getattr(request, "full_url", request)
    try:
        parsed = urlsplit(str(url))
    except ValueError:
        return str(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _unexpected_network_access(request, *args, **kwargs):
    raise AssertionError(f"unexpected network access: {_request_url(request)}")


def _unexpected_opener_access(opener, request, *args, **kwargs):
    return _unexpected_network_access(request)


def _unexpected_requests_access(session, method, url, *args, **kwargs):
    return _unexpected_network_access(url)


def _enter_rate_limiter_without_wait(rate_limiter):
    return rate_limiter


def _exit_rate_limiter_without_recording(_rate_limiter, *_args):
    return None


def _sleep_without_wait(*_args, **_kwargs):
    return None


def _module_requesters(plugin_module):
    requesters = [REQ.__wrapped__ if isinstance(REQ, LazyProxy) else REQ]
    for value in vars(plugin_module).values():
        if isinstance(value, requester):
            requesters.append(value)
        elif isinstance(value, LazyProxy):
            lazy_requester = value.__wrapped__
            if isinstance(lazy_requester, requester):
                requesters.append(lazy_requester)
        elif isinstance(value, LazyObject) and value.is_initialized and isinstance(value._object, requester):
            requesters.append(value._object)
    return list({id(req): req for req in requesters}.values())


def _method_cache_key(method, url):
    return sha256(f"{method}:{url}".encode()).hexdigest()


def _request_cache_url(url):
    parsed = urlsplit(str(url))
    query = parse_qsl(parsed.query, keep_blank_values=True)
    cache_query = [(key, value) for key, value in query if key != "_"]
    if cache_query == query:
        return str(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(cache_query), parsed.fragment))


def _post_cache_key(url, post):
    if isinstance(post, bytes):
        body = post
    elif isinstance(post, str):
        body = post.encode()
    elif isinstance(post, dict):
        body = urlencode(post, doseq=True).encode()
    else:
        body = json.dumps(post, sort_keys=True, default=str).encode()
    body_hash = sha256(body).hexdigest()
    return f"POST:{_request_cache_url(url)}:{body_hash}"


@contextmanager
def use_parser_cache(plugin_module, cache_path, allow_network):
    cache_directory = Path(cache_path).resolve()
    cache_path = f"{cache_directory}{os.sep}"
    methods_cache_path = cache_directory / "requester_methods.json"
    methods_cache = json.loads(methods_cache_path.read_text()) if methods_cache_path.is_file() else {}
    requesters = _module_requesters(plugin_module)

    originals = {}
    for req in requesters:
        originals[id(req)] = {name: getattr(req, name) for name in REQUESTER_ATTRIBUTES | {"dir_cache": None}}
        req.dir_cache = cache_path
        for name, value in REQUESTER_ATTRIBUTES.items():
            setattr(req, name, value)

    try:
        with ExitStack() as stack:
            original_get = requester.get
            original_head = requester.head
            original_geturl = requester.geturl

            def cached_get(req, url, *args, **kwargs):
                post = args[0] if args else kwargs.get("post")
                if "md5_file_cache" not in kwargs:
                    if post is not None:
                        kwargs["md5_file_cache"] = _post_cache_key(url, post)
                    else:
                        cache_url = _request_cache_url(url)
                        if cache_url != url:
                            kwargs["md5_file_cache"] = cache_url
                return original_get(req, url, *args, **kwargs)

            def cached_head(req, url):
                key = _method_cache_key("HEAD", url)
                if allow_network:
                    try:
                        result = original_head(req, url)
                    except FailOnGetResponse as error:
                        methods_cache[key] = {"code": error.code, "ok": False}
                        write_json(methods_cache_path, methods_cache)
                        raise
                    methods_cache[key] = {"ok": True}
                    write_json(methods_cache_path, methods_cache)
                    return result

                if key not in methods_cache:
                    return _unexpected_network_access(url)
                cached = methods_cache[key]
                if cached["ok"]:
                    return None
                error = urllib.error.HTTPError(url, cached["code"], "cached response", {}, BytesIO())
                raise FailOnGetResponse(error)

            def cached_geturl(req, url):
                key = _method_cache_key("GETURL", url)
                if allow_network:
                    result = original_geturl(req, url)
                    methods_cache[key] = {"result": result}
                    write_json(methods_cache_path, methods_cache)
                    return result

                if key not in methods_cache:
                    return _unexpected_network_access(url)
                return methods_cache[key]["result"]

            stack.enter_context(patch.object(requester, "get", cached_get))
            stack.enter_context(patch.object(requester, "head", cached_head))
            stack.enter_context(patch.object(requester, "geturl", cached_geturl))
            if not allow_network:
                stack.enter_context(patch.object(RateLimiter, "__enter__", _enter_rate_limiter_without_wait))
                stack.enter_context(patch.object(RateLimiter, "__exit__", _exit_rate_limiter_without_recording))
                if callable(getattr(plugin_module, "sleep", None)):
                    stack.enter_context(patch.object(plugin_module, "sleep", _sleep_without_wait))
                stack.enter_context(patch.object(time, "sleep", _sleep_without_wait))
                stack.enter_context(patch.object(urllib.request.OpenerDirector, "open", _unexpected_opener_access))
                stack.enter_context(patch("utils.requester.curl_response", side_effect=_unexpected_network_access))
                stack.enter_context(patch.object(requests.sessions.Session, "request", _unexpected_requests_access))
                stack.enter_context(patch.object(requester, "save", return_value=None))
            yield
    finally:
        for req in requesters:
            for name, value in originals[id(req)].items():
                setattr(req, name, value)


def standings_context_from_statistics(statistics):
    statistics = list(statistics)
    if not statistics:
        return StandingsContext(users=None, statistics=None)

    users = []
    statistics_by_key = {}
    for statistic in statistics:
        key = statistic.account.key
        users.append(key)
        statistics_by_key[key] = statistic.addition or {}
    return StandingsContext(users=users, statistics=statistics_by_key)


def contest_standings_context(contest):
    from ranking.models import Statistics

    statistics = (
        Statistics.objects
        .filter(contest=contest)
        .select_related("account")
        .order_by(F("place_as_int").asc(nulls_last=True), "pk")
    )
    return standings_context_from_statistics(statistics)


def get_standings(contest, cache_path, allow_network, users=None, statistics=None):
    contest = Contest.objects.select_related("resource__module").get(pk=contest.pk)
    plugin_module = contest.resource.plugin
    with use_parser_cache(plugin_module, cache_path, allow_network=allow_network), REQ:
        plugin = plugin_module.Statistic(contest=contest)
        return plugin.get_standings(users=deepcopy(users), statistics=deepcopy(statistics))


def fixture_contest_pk(fixture_path):
    objects = read_json(Path(fixture_path) / "db.json")
    contests = [obj["pk"] for obj in objects if obj["model"] == "clist.contest"]
    if len(contests) != 1:
        raise AssertionError(f"expected one clist.contest in {fixture_path / 'db.json'}, found {len(contests)}")
    return contests[0]


class ParserRegressionTestCase(TestCase):
    def run_fixture(self, fixture_path):
        fixture_path = Path(fixture_path)
        call_command("loaddata", fixture_path / "db.json", verbosity=0)
        contest = Contest.objects.select_related("resource__module").get(pk=fixture_contest_pk(fixture_path))

        context = contest_standings_context(contest)
        with materialized_http_cache(fixture_path) as cache_path:
            standings = get_standings(
                contest,
                cache_path,
                allow_network=False,
                users=context.users,
                statistics=context.statistics,
            )
        actual = normalize_standings(standings)
        expected = read_json(fixture_file_path(fixture_path, "expected_standings.json"))

        relative_path = fixture_path.relative_to(PARSER_FIXTURES_ROOT)
        assert_standings_equal(expected, actual, f"parser regression mismatch for {relative_path}")
