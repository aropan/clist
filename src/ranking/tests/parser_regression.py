import gzip
import json
import os
import urllib.request
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import NamedTuple
from unittest.mock import patch
from urllib.parse import quote, urlsplit, urlunsplit

import requests
from django.core.management import call_command
from django.test import TestCase
from lazy_object_proxy import Proxy as LazyProxy

from clist.models import Contest
from ranking.management.modules.common import REQ
from ranking.management.modules.excepts import FailOnGetResponse
from utils.lazy import LazyObject
from utils.requester import requester

PARSER_FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "parsers"
FIXTURE_FILENAMES = ("db.json", "expected_standings.json")

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


def fixture_path_for_contest(contest):
    return PARSER_FIXTURES_ROOT / fixture_component(contest.resource_id) / fixture_component(contest.pk)


def discover_parser_fixtures(root=PARSER_FIXTURES_ROOT):
    if not root.exists():
        return []
    fixtures = []
    for db_path in root.rglob("db.json"):
        fixture_path = db_path.parent
        if (
            all(fixture_file_path(fixture_path, filename).is_file() for filename in FIXTURE_FILENAMES)
            and (fixture_path / "httpcache").is_dir()
        ):
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


def write_json(path, data):
    path = Path(path)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(temporary_path, "wt") as output:
        json.dump(data, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
    temporary_path.replace(path)


def write_expected_standings(path, standings, compressed=False):
    filename = "expected_standings.json.gz" if compressed else "expected_standings.json"
    write_json(Path(path) / filename, normalize_standings(standings))


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
            original_head = requester.head
            original_geturl = requester.geturl

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

            stack.enter_context(patch.object(requester, "head", cached_head))
            stack.enter_context(patch.object(requester, "geturl", cached_geturl))
            if not allow_network:
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

    statistics = Statistics.objects.filter(contest=contest).select_related("account").order_by("pk")
    return standings_context_from_statistics(statistics)


def get_standings(contest, cache_path, allow_network, users=None, statistics=None):
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
    maxDiff = None

    def run_fixture(self, fixture_path):
        fixture_path = Path(fixture_path)
        call_command("loaddata", fixture_path / "db.json", verbosity=0)
        contest = Contest.objects.select_related("resource__module").get(pk=fixture_contest_pk(fixture_path))

        context = contest_standings_context(contest)
        standings = get_standings(
            contest,
            fixture_path / "httpcache",
            allow_network=False,
            users=context.users,
            statistics=context.statistics,
        )
        actual = normalize_standings(standings)
        expected = read_json(fixture_file_path(fixture_path, "expected_standings.json"))

        relative_path = fixture_path.relative_to(PARSER_FIXTURES_ROOT)
        self.assertEqual(expected, actual, f"parser regression mismatch for {relative_path}")  # noqa: PT009
