import gzip
import json
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from clist.models import Contest, ContestSeries, Resource
from ranking.management.commands.dump_parser_fixture import (
    Command,
    SelectedStatistics,
    contest_coverage_key,
    load_fixture_coverage,
    load_fixture_metadata,
)
from ranking.models import Account, Module, Statistics
from ranking.tests.parser_regression import (
    PARSER_FIXTURES_ROOT,
    discover_parser_fixtures,
    fixture_path_for_contest,
    fixture_resource_component,
    materialized_http_cache,
    pack_http_cache,
    parser_fixture_path,
)
from utils.attrdict import AttrDict
from utils.filesystem import PathOwner


class ParserFixtureCoverageTest(SimpleTestCase):
    def test_load_fixture_coverage(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory) / "1" / "2"
            cache_path = Path(temporary_directory) / "recording-cache"
            cache_path.mkdir()
            (cache_path / "page.html").write_text("cached response")
            fixture_path.mkdir(parents=True)
            pack_http_cache(cache_path, fixture_path / "httpcache.json.gz")
            (fixture_path / "expected_standings.json").write_text("{}")
            (fixture_path / "db.json").write_text(
                json.dumps([
                    {
                        "model": "clist.resource",
                        "pk": 1,
                        "fields": {"host": "example.com"},
                    },
                    {
                        "model": "clist.contest",
                        "pk": 2,
                        "fields": {
                            "resource": 1,
                            "key": "contest-key",
                            "kind": "algorithm",
                            "standings_kind": "scoring",
                            "invisible": False,
                            "is_rated": True,
                            "series": 3,
                            "with_medals": False,
                        },
                    },
                ])
            )

            combinations, contests = load_fixture_coverage(Path(temporary_directory))

        assert combinations == {(1, "algorithm", "scoring", False, True, False, False)}
        assert contests == {(1, 2)}

    def test_fixture_path_uses_encoded_resource_host(self):
        contest = AttrDict({"pk": 22, "resource": AttrDict({"host": "example.com/path_with_underscore"})})

        assert fixture_path_for_contest(contest) == (
            PARSER_FIXTURES_ROOT / "example.com__path%5Fwith%5Funderscore" / "22"
        )

    def test_fixture_resource_component_escapes_literal_underscores(self):
        assert fixture_resource_component("example.com/path_with_underscore") == (
            "example.com__path%5Fwith%5Funderscore"
        )
        assert fixture_resource_component("example.com__path/with_underscore") == (
            "example.com%5F%5Fpath__with%5Funderscore"
        )

    def test_repository_fixture_paths_are_canonical(self):
        fixture_paths = discover_parser_fixtures()

        assert fixture_paths
        for fixture_path in fixture_paths:
            metadata = load_fixture_metadata(fixture_path)
            assert fixture_path == parser_fixture_path(
                metadata["resource_host"],
                metadata["contest_id"],
            )


class ParserFixtureValidationTest(SimpleTestCase):
    def test_database_fixture_omits_contest_writers(self):
        contest = AttrDict({
            "resource": AttrDict({"module": object()}),
            "series_id": None,
        })
        serialized = json.dumps([
            {
                "model": "clist.contest",
                "pk": 1,
                "fields": {
                    "key": "contest",
                    "writers": [1, 2],
                },
            }
        ])

        with patch("ranking.management.commands.dump_parser_fixture.serializers.serialize", return_value=serialized):
            fixture = Command().serialize_database_fixture(contest)

        assert "writers" not in fixture[0]["fields"]

    def test_sensitive_regex_error_hides_match_by_default(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            (fixture_path / "payload.txt").write_bytes(b'access_token = "testsecret123"')

            with pytest.raises(CommandError) as error:
                Command().validate_recording(fixture_path)

        message = str(error.value)
        assert "refusing to keep a potential credential in payload.txt" in message
        assert "testsecret123" not in message
        assert "regex match at byte" not in message

    def test_sensitive_regex_error_can_show_match(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            (fixture_path / "payload.txt").write_bytes(b'access_token = "testsecret123"')

            with pytest.raises(CommandError) as error:
                Command().validate_recording(fixture_path, show_sensitive_matches=True)

        message = str(error.value)
        assert "refusing to keep a potential credential in payload.txt" in message
        assert "regex match at byte 0" in message
        assert "testsecret123" in message

    def test_sensitive_json_error_detects_secret_key(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            (fixture_path / "payload.txt").write_text('{"secret": "testsecret123"}')

            with pytest.raises(CommandError) as error:
                Command().validate_recording(fixture_path, show_sensitive_matches=True)

        message = str(error.value)
        assert "refusing to keep a potential credential in payload.txt" in message
        assert "JSON field $.secret=" in message
        assert "testsecret123" in message

    def test_sensitive_json_ignores_credential_like_text_in_affiliation(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            (fixture_path / "payload.txt").write_text(
                json.dumps({"StandingsData": [{"Affiliation": "Example password: public-value-123"}]})
            )

            Command().validate_recording(fixture_path)

    def test_sensitive_json_detects_credential_inside_string_value(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            (fixture_path / "payload.txt").write_text(
                json.dumps({"html": '<input name="x"> access_token=testsecret123'})
            )

            with pytest.raises(CommandError) as error:
                Command().validate_recording(fixture_path, show_sensitive_matches=True)

        message = str(error.value)
        assert "regex match in JSON value $.html" in message
        assert "testsecret123" in message

    def test_sensitive_json_detects_credential_inside_root_string(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            (fixture_path / "payload.txt").write_text(json.dumps("session_id=testsecret123"))

            with pytest.raises(CommandError) as error:
                Command().validate_recording(fixture_path, show_sensitive_matches=True)

        assert "regex match in JSON value $" in str(error.value)

    def test_sensitive_json_ignores_dynamic_result_and_problem_keys(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            (fixture_path / "payload.txt").write_text(
                json.dumps({
                    "result": {
                        "snowysecret": {
                            "member": "snowysecret",
                            "problems": {"access_token": {"result": "+"}},
                        }
                    }
                })
            )

            Command().validate_recording(fixture_path)

    def test_sensitive_json_checks_fields_inside_dynamic_maps(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            (fixture_path / "payload.txt").write_text(
                json.dumps({"result": {"snowysecret": {"session_token": "testsecret123"}}})
            )

            with pytest.raises(CommandError) as error:
                Command().validate_recording(fixture_path, show_sensitive_matches=True)

        assert "JSON field $.result.snowysecret.session_token=" in str(error.value)

    def test_codingame_httpcache_redacts_public_test_session_handle(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            httpcache_path = fixture_path / "httpcache"
            httpcache_path.mkdir()
            payload_path = httpcache_path / "leaderboard.html"
            payload_path.write_text(json.dumps({"users": [{"testSessionHandle": "public-test-session-handle"}]}))

            command = Command()
            assert command.sanitize_fixture_file(payload_path)
            payload = json.loads(payload_path.read_text())
            command.validate_recording(fixture_path, resource_host="codingame.com")

        assert payload["users"][0]["testSessionHandle"] == "<redacted-test-session-handle>"

    def test_public_test_session_handle_allowance_is_scoped_to_codingame_httpcache(self):
        cases = (
            ("codingame.com", "leaderboard.html"),
            ("example.com", "httpcache/leaderboard.html"),
        )
        for resource_host, relative_path in cases:
            with (
                self.subTest(resource_host=resource_host, relative_path=relative_path),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                fixture_path = Path(temporary_directory)
                payload_path = fixture_path / relative_path
                payload_path.parent.mkdir(parents=True, exist_ok=True)
                payload_path.write_text(
                    json.dumps({"users": [{"testSessionHandle": "<redacted-test-session-handle>"}]})
                )

                with pytest.raises(CommandError):
                    Command().validate_recording(fixture_path, resource_host=resource_host)

    def test_codingame_httpcache_still_rejects_other_session_fields(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            httpcache_path = fixture_path / "httpcache"
            httpcache_path.mkdir()
            (httpcache_path / "leaderboard.html").write_text(
                json.dumps({"users": [{"sessionToken": "test-session-token"}]})
            )

            with pytest.raises(CommandError):
                Command().validate_recording(fixture_path, resource_host="codingame.com")

    def test_codingame_httpcache_allows_public_static_javascript(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            httpcache_path = fixture_path / "httpcache"
            httpcache_path.mkdir()
            (httpcache_path / "hash_static.codingame.com_app.js.html").write_text(
                'const form = {password: "public-placeholder"};'
            )

            Command().validate_recording(fixture_path, resource_host="codingame.com")

    def test_codingame_httpcache_allows_compressed_public_static_javascript(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            httpcache_path = fixture_path / "httpcache"
            httpcache_path.mkdir()
            with gzip.open(
                httpcache_path / "hash_static.codingame.com_app.js.html.gz",
                "wt",
            ) as output_file:
                output_file.write('const form = {password: "public-placeholder"};')

            Command().validate_recording(fixture_path, resource_host="codingame.com")

    def test_public_static_javascript_allowance_is_scoped_to_codingame_httpcache(self):
        cases = (
            ("codingame.com", "hash_static.codingame.com_app.js.html"),
            ("example.com", "httpcache/hash_static.codingame.com_app.js.html"),
            ("codingame.com", "httpcache/page.html"),
        )
        for resource_host, relative_path in cases:
            with (
                self.subTest(resource_host=resource_host, relative_path=relative_path),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                fixture_path = Path(temporary_directory)
                payload_path = fixture_path / relative_path
                payload_path.parent.mkdir(parents=True, exist_ok=True)
                payload_path.write_text('const form = {password: "public-placeholder"};')

                with pytest.raises(CommandError):
                    Command().validate_recording(fixture_path, resource_host=resource_host)

    def test_public_static_javascript_still_checks_environment_secrets(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            httpcache_path = fixture_path / "httpcache"
            httpcache_path.mkdir()
            (httpcache_path / "hash_static.codingame.com_app.js.html").write_text(
                'const form = {password: "test-environment-secret"};'
            )

            with (
                patch.dict("os.environ", {"API_TOKEN": "test-environment-secret"}),
                pytest.raises(CommandError, match="refusing to keep an environment secret"),
            ):
                Command().validate_recording(fixture_path, resource_host="codingame.com")

    def test_sensitive_regex_ignores_secret_inside_plain_identifier(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            (fixture_path / "payload.txt").write_text(
                '"spectator_ranklist": "Warmup_kevinxiehk_vs_snowysecret_TaQsJnPP"'
            )

            Command().validate_recording(fixture_path, show_sensitive_matches=True)

    def test_sensitive_regex_ignores_secret_prefixed_handle(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            (fixture_path / "payload.txt").write_text('{"handle": "secret_way_popa"}')

            Command().validate_recording(fixture_path, show_sensitive_matches=True)

    def test_verbose_level_three_is_dimmed_when_color_is_enabled(self):
        stdout = StringIO()
        command = Command(stdout=stdout, force_color=True)
        command.set_verbosity(3)

        command.verbose("debug detail", level=3)

        assert "\033[2m" in stdout.getvalue()
        assert "debug detail" in stdout.getvalue()

    def test_environment_secret_error_can_show_match(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            (fixture_path / "payload.txt").write_bytes(b"prefix test-environment-secret suffix")

            with (
                patch.dict("os.environ", {"API_TOKEN": "test-environment-secret"}),
                pytest.raises(CommandError) as error,
            ):
                Command().validate_recording(fixture_path, show_sensitive_matches=True)

        message = str(error.value)
        assert "refusing to keep an environment secret in payload.txt" in message
        assert "environment API_TOKEN='test-environment-secret'" in message

    def test_environment_secret_error_hides_match_by_default(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            (fixture_path / "payload.txt").write_bytes(b"prefix test-environment-secret suffix")

            with (
                patch.dict("os.environ", {"API_TOKEN": "test-environment-secret"}),
                pytest.raises(CommandError) as error,
            ):
                Command().validate_recording(fixture_path)

        message = str(error.value)
        assert "refusing to keep an environment secret in payload.txt" in message
        assert "test-environment-secret" not in message

    def test_environment_secret_is_detected_inside_json_value(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            (fixture_path / "payload.txt").write_text(
                json.dumps({"Affiliation": "prefix test-environment-secret suffix"})
            )

            with (
                patch.dict("os.environ", {"API_TOKEN": "test-environment-secret"}),
                pytest.raises(CommandError) as error,
            ):
                Command().validate_recording(fixture_path)

        message = str(error.value)
        assert "refusing to keep an environment secret in payload.txt" in message
        assert "test-environment-secret" not in message


class ParserFixtureStatisticsSelectionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()
        cls.resource = Resource.objects.create(
            host="selection.example.com",
            enable=True,
            url="https://selection.example.com/",
            color="#336699",
            icon_file="resources/test.png",
            icon_updated_at=cls.now,
        )
        Module.objects.create(
            resource=cls.resource,
            path="ranking.management.modules.common",
            long_contest_idle=timedelta(hours=6),
            shortly_after=timedelta(minutes=30),
            delay_shortly_after=timedelta(minutes=5),
            max_delay_after_end=timedelta(hours=1),
            delay_on_error=timedelta(hours=1),
        )
        cls.contest = Contest.objects.create(
            resource=cls.resource,
            title="selection",
            start_time=cls.now - timedelta(hours=2),
            end_time=cls.now - timedelta(hours=1),
            duration_in_secs=3600,
            url="https://selection.example.com/contest",
            key="selection",
            host=cls.resource.host,
            parsed_time=cls.now,
        )

    def create_statistic(self, key, addition, place):
        account = Account.objects.create(resource=self.resource, key=key)
        return Statistics.objects.create(
            account=account,
            contest=self.contest,
            resource=self.resource,
            addition=addition,
            place_as_int=place,
        )

    def test_select_statistics_for_fixture_uses_new_nested_addition_keys(self):
        self.create_statistic(
            "alice",
            {
                "rating": {"new": 1500},
                "problems": {"A": {"verdict": "OK"}},
            },
            1,
        )
        self.create_statistic("bob", {"rating": {"new": 1600}}, 2)
        self.create_statistic("carol", {"problems": {"B": {"verdict": "WA"}}}, 3)
        self.create_statistic("dave", {}, 4)

        selected = Command().select_statistics_for_fixture(self.contest)

        assert selected.users == ["alice", "carol"]
        assert selected.statistics_by_key == {
            "alice": {
                "rating": {"new": 1500},
                "problems": {"A": {"verdict": "OK"}},
            },
            "carol": {"problems": {"B": {"verdict": "WA"}}},
        }
        assert "rating.new" in selected.addition_keys
        assert "problems.A.verdict" in selected.addition_keys
        assert "problems.B.verdict" in selected.addition_keys

    def test_database_fixture_includes_selected_accounts_and_statistics(self):
        self.resource.accounts_fields = {
            "types": {"rating": ["int"]},
            "variables": {"LEETCODE_SESSION": {"help": "Session cookie", "regex": ".+"}},
        }
        self.resource.save(update_fields=["accounts_fields"])
        statistic = self.create_statistic("alice", {"rating": {"new": 1500}}, 1)
        statistic.account.info = {
            "__typename": "User",
            "_rating_time": 123,
            "birthday": "2000-01-01",
            "emailAddress": "alice@example.com",
            "phone_number": "+123456789",
            "profile_url": {"_handle": "alice", "slug": "alice"},
            "outdated_": {"slogan": "alice@example.com"},
            "variables_": {"LEETCODE_SESSION": {"value": "session-value"}},
            "public_field": {"nested": "value"},
        }
        statistic.account.submissions_info = {
            "_private_cursor": 1,
            "session_id": "session-value",
            "public_cursor": 2,
        }
        statistic.account.rating_prediction = {
            "_private_rank": 1,
            "email": "alice@example.com",
            "public_rank": 2,
        }
        statistic.account.save(update_fields=["info", "submissions_info", "rating_prediction"])
        selected = SelectedStatistics(
            statistics=[statistic],
            users=["alice"],
            statistics_by_key={"alice": statistic.addition},
            addition_keys={"rating", "rating.new"},
        )

        fixture = Command().serialize_database_fixture(self.contest, selected.statistics)
        models = [obj["model"] for obj in fixture]

        assert "ranking.account" in models
        assert "ranking.statistics" in models
        account = next(obj for obj in fixture if obj["model"] == "ranking.account")
        resource = next(obj for obj in fixture if obj["model"] == "clist.resource")
        statistic_object = next(obj for obj in fixture if obj["model"] == "ranking.statistics")
        assert resource["fields"]["accounts_fields"] == {"types": {"rating": ["int"]}}
        assert "coders" not in account["fields"]
        assert account["fields"]["duplicate"] is None
        assert account["fields"]["related"] is None
        assert account["fields"]["info"] == {
            "profile_url": {"slug": "alice"},
            "public_field": {"nested": "value"},
        }
        assert account["fields"]["submissions_info"] == {"public_cursor": 2}
        assert account["fields"]["rating_prediction"] == {"public_rank": 2}
        assert statistic_object["fields"]["account"] == statistic.account_id
        assert statistic_object["fields"]["addition"] == {"rating": {"new": 1500}}
        assert statistic_object["fields"]["related"] is None

    def test_fixture_public_data_is_redacted_but_calendar_uid_is_preserved(self):
        command = Command()
        google_api_key = "AIza" + "x" * 35
        payload = {
            "contact": "alice@example.com",
            "phone": "+123 456 7890",
            "link": "tel:+1234567890",
            "calendar": "calendar@group.calendar.google.com",
            "script": f"key={google_api_key}",
            "testSessionHandle": "public-test-session-handle",
        }
        expected = {
            "contact": "<redacted-email>",
            "phone": "<redacted-phone>",
            "link": "tel:<redacted-phone>",
            "calendar": "calendar@group.calendar.google.com",
            "script": "key=<redacted-google-api-key>",
            "testSessionHandle": "<redacted-test-session-handle>",
        }

        assert command.sanitize_fixture_data(payload) == expected
        assert json.loads(command.sanitize_fixture_bytes(json.dumps(payload).encode())) == expected

    def test_validation_rejects_unsanitized_public_data(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            (fixture_path / "payload.txt").write_text('{"contact": "alice@example.com"}')

            with pytest.raises(CommandError, match="refusing to keep potentially sensitive data"):
                Command().validate_recording(fixture_path)

    def test_validation_checks_compressed_public_data(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            with gzip.open(fixture_path / "payload.json.gz", "wt") as output_file:
                json.dump({"contact": "alice@example.com"}, output_file)

            with pytest.raises(CommandError, match="refusing to keep potentially sensitive data"):
                Command().validate_recording(fixture_path)

    def test_validation_checks_bundled_http_cache_content(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory)
            cache_path = fixture_path / "httpcache"
            cache_path.mkdir()
            payload_path = cache_path / "payload.json"
            payload_path.write_text('{"contact": "alice@example.com"}')
            pack_http_cache(cache_path, fixture_path / "httpcache.json.gz")
            payload_path.unlink()
            cache_path.rmdir()

            with pytest.raises(CommandError, match=r"potentially sensitive data in httpcache/payload\.json"):
                Command().validate_recording(fixture_path)


class ParserFixtureRecordingTest(SimpleTestCase):
    def test_gzip_file_is_deterministic(self):
        command = Command()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_path = root / "first.html"
            second_path = root / "second.html"
            first_path.write_bytes(b'{"result": {"alice": 1}}')
            second_path.write_bytes(b'{"result": {"alice": 1}}')

            first_gzip = command.gzip_file(first_path).read_bytes()
            second_gzip = command.gzip_file(second_path).read_bytes()

        assert first_gzip == second_gzip
        assert first_gzip[:3] == b"\x1f\x8b\x08"
        assert first_gzip[3] & 0x08 == 0
        assert first_gzip[4:8] == b"\0\0\0\0"

    def test_standings_mismatch_error_includes_diff_path_and_values(self):
        command = Command()
        live = {"result": {"alice": {"solving": 1}}, "problems": [{"short": "A"}]}
        replayed = {"result": {"alice": {"solving": 2}}, "problems": [{"short": "A"}]}

        with pytest.raises(CommandError) as error:
            command.assert_same_normalized_standings(live, replayed, "standings mismatch")

        message = str(error.value)
        assert "standings mismatch" in message
        assert "$.result.alice.solving" in message
        assert "live=1" in message
        assert "replay=2" in message

    def test_standings_mismatch_verbose_output_lists_more_diffs(self):
        stderr = StringIO()
        command = Command(stderr=stderr)
        command.set_verbosity(2)
        live = {
            "result": {
                "alice": {"addition": {"rating": 1500}, "solving": 1},
                "bob": {"addition": {"medal": "gold"}, "solving": 2},
            },
            "problems": [{"short": "A"}],
        }
        replayed = {
            "result": {
                "alice": {"addition": {"rating": 1500}, "solving": 3},
                "bob": {"addition": {"medal": "gold"}, "solving": 4},
            },
            "problems": [{"short": "B"}],
        }

        with pytest.raises(CommandError):
            command.assert_same_normalized_standings(live, replayed, "standings mismatch")

        output = stderr.getvalue()
        assert "Normalized standings differ:" in output
        assert "$.result.alice.solving" in output
        assert "$.result.bob.solving" in output
        assert "$.problems[0].short" in output

    def test_verbose_recording_shows_offline_replay_before_failure(self):
        stdout = StringIO()
        command = Command(stdout=stdout)
        command.set_verbosity(2)
        command.serialize_database_fixture = Mock(return_value=[])
        command.select_statistics_for_fixture = Mock(
            return_value=SelectedStatistics(
                statistics=[],
                users=["alice"],
                statistics_by_key={"alice": {"rating": {"new": 1500}}},
                addition_keys={"rating", "rating.new"},
            )
        )
        standings = {"result": {"alice": {"solving": 1}}, "problems": [{"short": "A"}]}

        def get_standings(contest, cache_path, allow_network, users=None, statistics=None):
            assert users == ["alice"]
            assert statistics == {"alice": {"rating": {"new": 1500}}}
            if allow_network:
                (Path(cache_path) / "page.html").write_text("cached")
                return standings
            raise AssertionError("unexpected network access: https://example.com/fallback.html")

        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory) / "example.com" / "contest"
            with (
                patch("ranking.management.commands.dump_parser_fixture.get_standings", side_effect=get_standings),
                pytest.raises(AssertionError, match="unexpected network access"),
            ):
                command.record_fixture(object(), fixture_path)

        output = stdout.getvalue()
        assert "run parser with network enabled" in output
        assert "write golden standings snapshot" in output
        assert "run immediate offline replay" in output

    def test_recorded_fixture_bundles_http_cache(self):
        command = Command()
        command.serialize_database_fixture = Mock(return_value=[])
        command.select_statistics_for_fixture = Mock(
            return_value=SelectedStatistics(
                statistics=[],
                users=["alice"],
                statistics_by_key={"alice": {"rating": {"new": 1500}}},
                addition_keys={"rating", "rating.new"},
            )
        )
        standings = {"result": {"alice": {"solving": 1}}, "problems": [{"short": "A"}]}

        def get_standings(contest, cache_path, allow_network, users=None, statistics=None):
            assert users == ["alice"]
            assert statistics == {"alice": {"rating": {"new": 1500}}}
            if allow_network:
                (Path(cache_path) / "page.html").write_text('{"ok": true}')
            return standings

        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory) / "1" / "2"
            with (
                patch("ranking.management.commands.dump_parser_fixture.get_standings", side_effect=get_standings),
                patch.object(command, "make_fixture_owned_by_workspace_user"),
            ):
                command.record_fixture(object(), fixture_path)

            assert not (fixture_path / "expected_standings.json").exists()
            assert (fixture_path / "expected_standings.json.gz").is_file()
            assert not (fixture_path / "httpcache").exists()
            assert (fixture_path / "httpcache.json.gz").is_file()
            with gzip.open(fixture_path / "expected_standings.json.gz", "rt") as input_file:
                assert json.load(input_file)["result"] == {"alice": {"solving": 1}}
            with materialized_http_cache(fixture_path) as cache_path:
                assert json.loads((cache_path / "page.html").read_text()) == {"ok": True}

    def test_recording_sanitizes_cache_and_expected_standings(self):
        command = Command()
        command.serialize_database_fixture = Mock(return_value=[])
        command.select_statistics_for_fixture = Mock(
            return_value=SelectedStatistics(
                statistics=[],
                users=["alice"],
                statistics_by_key={"alice": {"name": "alice@example.com"}},
                addition_keys={"name"},
            )
        )

        def get_standings(contest, cache_path, allow_network, users=None, statistics=None):
            cache_path = Path(cache_path)
            if allow_network:
                (cache_path / "page.html").write_text('{"name": "alice@example.com"}')
                name = "alice@example.com"
            else:
                page_path = cache_path / "page.html"
                if page_path.is_file():
                    page = page_path.read_text()
                else:
                    with gzip.open(f"{page_path}.gz", "rt") as input_file:
                        page = input_file.read()
                name = json.loads(page)["name"]
            return {"result": {"alice": {"name": name}}}

        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_path = Path(temporary_directory) / "1" / "2"
            with (
                patch("ranking.management.commands.dump_parser_fixture.get_standings", side_effect=get_standings),
                patch.object(command, "make_fixture_owned_by_workspace_user"),
            ):
                command.record_fixture(object(), fixture_path)

            with gzip.open(fixture_path / "expected_standings.json.gz", "rt") as input_file:
                expected = json.load(input_file)
            with materialized_http_cache(fixture_path) as cache_path:
                cached = json.loads((cache_path / "page.html").read_text())

        assert expected["result"]["alice"]["name"] == "<redacted-email>"
        assert cached["name"] == "<redacted-email>"

    def test_recorded_fixture_is_chowned_to_workspace_owner_when_running_as_root(self):
        command = Command()

        with tempfile.TemporaryDirectory() as temporary_directory:
            fixtures_root = Path(temporary_directory) / "parsers"
            workspace_root = Path(temporary_directory) / "workspace"
            workspace_root.mkdir()
            fixture_path = fixtures_root / "11" / "22"
            fixture_path.mkdir(parents=True)
            (fixture_path / "db.json").write_text("{}")

            with (
                patch("ranking.management.commands.dump_parser_fixture.PARSER_FIXTURES_ROOT", fixtures_root),
                patch("ranking.management.commands.dump_parser_fixture.settings.BASE_DIR", workspace_root),
                patch("utils.filesystem.os.geteuid", return_value=0),
                patch("utils.filesystem.os.chown") as chown,
                patch("utils.filesystem.path_owner", return_value=PathOwner(workspace_root, 1000, 1000)),
            ):
                command.make_fixture_owned_by_workspace_user(fixture_path)

        chowned_paths = [call.args[0] for call in chown.call_args_list]
        assert fixtures_root in chowned_paths
        assert fixtures_root / "11" in chowned_paths
        assert fixture_path in chowned_paths
        assert fixture_path / "db.json" in chowned_paths
        assert all(call.args[1:] == (1000, 1000) for call in chown.call_args_list)
        assert all(call.kwargs == {"follow_symlinks": False} for call in chown.call_args_list)

    def test_recorded_fixture_is_not_chowned_when_not_running_as_root(self):
        command = Command()

        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch("utils.filesystem.os.geteuid", return_value=1000),
            patch("utils.filesystem.os.chown") as chown,
        ):
            command.make_fixture_owned_by_workspace_user(Path(temporary_directory))

        chown.assert_not_called()

    def test_recorded_fixture_warns_when_workspace_owner_is_root(self):
        stderr = StringIO()
        command = Command(stderr=stderr)

        with tempfile.TemporaryDirectory() as temporary_directory:
            fixtures_root = Path(temporary_directory) / "parsers"
            workspace_root = Path(temporary_directory) / "workspace"
            workspace_root.mkdir()
            fixture_path = fixtures_root / "11" / "22"
            fixture_path.mkdir(parents=True)

            with (
                patch("ranking.management.commands.dump_parser_fixture.PARSER_FIXTURES_ROOT", fixtures_root),
                patch("ranking.management.commands.dump_parser_fixture.settings.BASE_DIR", workspace_root),
                patch("utils.filesystem.os.geteuid", return_value=0),
                patch("utils.filesystem.os.chown") as chown,
                patch("utils.filesystem.path_owner", return_value=PathOwner(workspace_root, 0, 0)),
            ):
                command.make_fixture_owned_by_workspace_user(fixture_path)

        chown.assert_not_called()
        assert "Could not infer a non-root workspace owner" in stderr.getvalue()
        assert "copied production checkouts" in stderr.getvalue()


class ParserFixtureSuggestionsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()
        cls.resource = cls.create_resource("codeforces.com")
        cls.extra_suggestion_resource = cls.create_resource("luogu.com.cn")
        cls.annual_resource = cls.create_resource("annual.example.com")
        cls.series = ContestSeries.objects.create(name="Belarusian IOI", short="byio")

    @classmethod
    def create_resource(cls, host):
        resource = Resource.objects.create(
            host=host,
            enable=True,
            url=f"https://{host}/",
            color="#336699",
            icon_file="resources/test.png",
            icon_updated_at=cls.now,
        )
        Module.objects.create(
            resource=resource,
            path="ranking.management.modules.common",
            max_delay_after_end=timedelta(hours=1),
            delay_on_error=timedelta(hours=1),
        )
        return resource

    @classmethod
    def create_contest(cls, resource, key, end_time, **kwargs):
        return Contest.objects.create(
            resource=resource,
            title=key,
            start_time=end_time - timedelta(hours=1),
            end_time=end_time,
            duration_in_secs=3600,
            url=f"https://{resource.host}/{key}",
            key=key,
            host=resource.host,
            parsed_time=cls.now,
            **kwargs,
        )

    @classmethod
    def create_fixture_statistic(cls, contest, addition=None):
        account = Account.objects.create(resource=contest.resource, key=f"fixture-user-{contest.pk}")
        return Statistics.objects.create(
            account=account,
            contest=contest,
            resource=contest.resource,
            addition={"fixture": True} if addition is None else addition,
        )

    def create_candidates(self):
        combination_kwargs = {
            "kind": "algorithm",
            "standings_kind": "scoring",
            "is_rated": True,
        }
        older = self.create_contest(
            self.resource,
            "older",
            self.now - timedelta(days=2),
            **combination_kwargs,
        )
        newer = self.create_contest(
            self.resource,
            "newer",
            self.now - timedelta(days=1),
            **combination_kwargs,
        )
        old_annual = self.create_contest(
            self.annual_resource,
            "annual-2024",
            self.now - timedelta(days=2),
            series=self.series,
        )
        new_annual = self.create_contest(
            self.annual_resource,
            "annual-2025",
            self.now - timedelta(days=1),
            series=self.series,
        )
        for contest in (older, newer, old_annual, new_annual):
            self.create_fixture_statistic(contest)
        return older, newer, old_annual, new_annual

    def test_candidates_are_latest_per_combination_and_annual_series(self):
        older, newer, old_annual, new_annual = self.create_candidates()
        extra_suggestion = self.create_contest(
            self.extra_suggestion_resource,
            "luogu",
            self.now - timedelta(days=1),
            kind="algorithm",
            standings_kind="scoring",
            is_rated=True,
        )
        self.create_fixture_statistic(extra_suggestion)

        combinations, annual = Command().suggestion_candidates()
        combination_ids = {contest.pk for contest in combinations}
        annual_ids = {contest.pk for contest in annual}

        assert newer.pk in combination_ids
        assert extra_suggestion.pk in combination_ids
        assert older.pk not in combination_ids
        assert new_annual.pk in annual_ids
        assert old_annual.pk not in annual_ids

    def test_candidates_fall_back_to_older_contest_with_addition_statistics(self):
        combination_kwargs = {
            "kind": "algorithm",
            "standings_kind": "scoring",
            "is_rated": True,
        }
        older = self.create_contest(
            self.resource,
            "older-with-statistics",
            self.now - timedelta(days=2),
            **combination_kwargs,
        )
        self.create_fixture_statistic(older)
        newer = self.create_contest(
            self.resource,
            "newer-with-empty-statistics",
            self.now - timedelta(days=1),
            **combination_kwargs,
        )
        self.create_fixture_statistic(newer, addition={})

        combinations, _ = Command().suggestion_candidates()
        combination_ids = {contest.pk for contest in combinations}

        assert older.pk in combination_ids
        assert newer.pk not in combination_ids

    def test_candidates_can_be_filtered_by_resource(self):
        _, newer, _, new_annual = self.create_candidates()

        args = AttrDict({
            "contest_id": None,
            "resource": "annual.example.com",
            "resource_id": None,
            "contest_key": None,
        })
        combinations, annual = Command().suggestion_candidates(args)
        combination_ids = {contest.pk for contest in combinations}
        annual_ids = {contest.pk for contest in annual}

        assert newer.pk not in combination_ids
        assert new_annual.pk in combination_ids
        assert annual_ids == {new_annual.pk}

    def test_candidates_can_be_filtered_by_resource_id(self):
        _, newer, _, new_annual = self.create_candidates()

        args = AttrDict({
            "contest_id": None,
            "resource": None,
            "resource_id": self.annual_resource.pk,
            "contest_key": None,
        })
        combinations, annual = Command().suggestion_candidates(args)
        combination_ids = {contest.pk for contest in combinations}
        annual_ids = {contest.pk for contest in annual}

        assert newer.pk not in combination_ids
        assert new_annual.pk in combination_ids
        assert annual_ids == {new_annual.pk}

    def test_get_contest_can_use_resource_id(self):
        _, newer, _, _ = self.create_candidates()

        args = AttrDict({
            "contest_id": None,
            "resource": None,
            "resource_id": self.resource.pk,
            "contest_key": newer.key,
        })

        assert Command().get_contest(args) == newer

    def test_existing_fixture_path_is_found_by_ids(self):
        _, newer, _, _ = self.create_candidates()

        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_root = Path(temporary_directory)
            fixture_path = fixture_root / str(newer.resource_id) / str(newer.pk)
            fixture_path.mkdir(parents=True)
            (fixture_path / "expected_standings.json").write_text("{}")
            (fixture_path / "db.json").write_text(
                json.dumps([
                    {
                        "model": "clist.resource",
                        "pk": newer.resource_id,
                        "fields": {"host": newer.resource.host},
                    },
                    {
                        "model": "clist.contest",
                        "pk": newer.pk,
                        "fields": {
                            "resource": newer.resource_id,
                            "key": newer.key,
                        },
                    },
                ])
            )

            with patch(
                "ranking.management.commands.dump_parser_fixture.discover_parser_fixtures",
                return_value=[fixture_path],
            ):
                assert Command().fixture_path_for_recording(newer) == fixture_path

    def test_update_suggestions_continues_after_individual_failure(self):
        _, newer, _, new_annual = self.create_candidates()
        stdout = StringIO()
        stderr = StringIO()
        command = Command(stdout=stdout, stderr=stderr)

        def record_fixture(contest, fixture_path, show_sensitive_matches=False):
            if contest == newer:
                raise CommandError("recording failed")

        command.record_fixture = Mock(side_effect=record_fixture)
        with (
            patch(
                "ranking.management.commands.dump_parser_fixture.load_fixture_coverage",
                return_value=(set(), set()),
            ),
            pytest.raises(CommandError, match="failed to record 1 of 2 fixtures"),
        ):
            command.suggest_fixtures(update=True)

        output = stdout.getvalue()
        assert [call.args[0] for call in command.record_fixture.call_args_list] == [newer, new_annual]
        assert "docker compose exec" not in output
        assert "Parser fixture coverage" in output
        assert "parser variants: 0/1 covered" in output
        assert "annual latest:   0/1 covered" in output
        assert "Missing parser fixtures (2)" in output
        assert f"codeforces.com [resource_id={self.resource.pk}] (1)" in output
        assert f"contest_id={newer.pk}, key=newer" in output
        assert "variant: kind=algorithm, standings=scoring, hidden=no, rated=yes, series=no, medals=no" in output
        assert "annual:  series=byio" in output
        assert "1 recorded, 1 failed" in output
        assert "Failed codeforces.com/newer" in stderr.getvalue()
        assert "Traceback (most recent call last)" not in stderr.getvalue()

    def test_annual_latest_is_covered_by_older_fixture_with_same_variant(self):
        _, newer, old_annual, new_annual = self.create_candidates()
        stdout = StringIO()
        command = Command(stdout=stdout)

        with patch(
            "ranking.management.commands.dump_parser_fixture.load_fixture_coverage",
            return_value=(
                {contest_coverage_key(newer), contest_coverage_key(old_annual)},
                {(old_annual.resource_id, old_annual.pk)},
            ),
        ):
            command.suggest_fixtures()

        output = stdout.getvalue()
        assert "parser variants: 1/1 covered" in output
        assert "annual latest:   1/1 covered" in output
        assert "No parser fixtures need to be added." in output
        assert f"contest_id={new_annual.pk}" not in output

    def test_force_update_suggestions_records_already_covered_fixtures(self):
        _, newer, _, new_annual = self.create_candidates()
        stdout = StringIO()
        command = Command(stdout=stdout)
        command.record_fixture = Mock()

        with patch(
            "ranking.management.commands.dump_parser_fixture.load_fixture_coverage",
            return_value=(
                {contest_coverage_key(newer)},
                {(new_annual.resource_id, new_annual.pk)},
            ),
        ):
            command.suggest_fixtures(update=True, force_update=True)

        assert [call.args[0] for call in command.record_fixture.call_args_list] == [newer, new_annual]
        output = stdout.getvalue()
        assert "parser variants: 1/1 covered" in output
        assert "annual latest:   1/1 covered" in output
        assert "selected:" in output
        assert "Parser fixtures selected for force update (2)" in output
        assert "update variant: kind=algorithm, standings=scoring, hidden=no, rated=yes, series=no, medals=no" in output
        assert "update annual:  series=byio" in output

    def test_update_suggestions_can_show_error_traceback(self):
        _, newer, _, _ = self.create_candidates()
        stdout = StringIO()
        stderr = StringIO()
        command = Command(stdout=stdout, stderr=stderr)

        def record_fixture(contest, fixture_path, show_sensitive_matches=False):
            if contest == newer:
                raise CommandError("recording failed")

        command.record_fixture = Mock(side_effect=record_fixture)
        with (
            patch(
                "ranking.management.commands.dump_parser_fixture.load_fixture_coverage",
                return_value=(set(), set()),
            ),
            pytest.raises(CommandError, match="failed to record 1 of 2 fixtures"),
        ):
            command.suggest_fixtures(update=True, show_error_traceback=True)

        error_output = stderr.getvalue()
        assert "Traceback (most recent call last)" in error_output
        assert 'raise CommandError("recording failed")' in error_output
        assert "recording failed" in error_output
        assert "local_marker" not in error_output

    def test_update_suggestions_can_show_error_locals_with_explicit_flag(self):
        _, newer, _, _ = self.create_candidates()
        stdout = StringIO()
        stderr = StringIO()
        command = Command(stdout=stdout, stderr=stderr)

        def record_fixture(contest, fixture_path, show_sensitive_matches=False):
            local_marker = "debug-local-value"
            if local_marker and contest == newer:
                raise TypeError("broken parser")

        command.record_fixture = Mock(side_effect=record_fixture)
        with (
            patch(
                "ranking.management.commands.dump_parser_fixture.load_fixture_coverage",
                return_value=(set(), set()),
            ),
            pytest.raises(CommandError, match=r"failed to record 1 of 1 attempted fixtures \(1 skipped\)"),
        ):
            command.suggest_fixtures(update=True, fail_fast=True, show_error_locals=True)

        error_output = stderr.getvalue()
        assert "Traceback (most recent call last)" in error_output
        assert "local_marker = 'debug-local-value'" in error_output
        assert "TypeError: broken parser" in error_output

    def test_update_suggestions_can_stop_after_first_failure(self):
        _, newer, _, _ = self.create_candidates()
        stdout = StringIO()
        stderr = StringIO()
        command = Command(stdout=stdout, stderr=stderr)

        def record_fixture(contest, fixture_path, show_sensitive_matches=False):
            if contest == newer:
                raise CommandError("recording failed")

        command.record_fixture = Mock(side_effect=record_fixture)
        with (
            patch(
                "ranking.management.commands.dump_parser_fixture.load_fixture_coverage",
                return_value=(set(), set()),
            ),
            pytest.raises(CommandError, match=r"failed to record 1 of 1 attempted fixtures \(1 skipped\)"),
        ):
            command.suggest_fixtures(update=True, fail_fast=True)

        assert [call.args[0] for call in command.record_fixture.call_args_list] == [newer]
        assert "Batch recording stopped: 0 recorded, 1 failed, 1 skipped" in stdout.getvalue()
        assert "Failed codeforces.com/newer" in stderr.getvalue()
        assert "Stopping after first failure because --fail-fast is set." in stderr.getvalue()
