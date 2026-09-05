import ast
import logging
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from clist.models import Contest, Resource
from ranking.management.commands import parse_statistic
from ranking.management.commands.calculate_rating_prediction import ELO_MMR_RATING_FIELDS
from ranking.management.commands.parse_statistic import Command, get_standings_log_summary, log_long_operation
from ranking.management.modules.common import BaseModule
from ranking.models import Module, Statistics
from ranking.tests import test_calculate_rating_prediction


class ParseStatisticDiagnosticsTest(SimpleTestCase):
    def test_legacy_channel_handler_and_tqdm_monkeypatch_are_removed(self):
        assert not hasattr(parse_statistic, "ChannelLayerHandler")
        assert not hasattr(parse_statistic, "_tqdm")
        assert not hasattr(parse_statistic, "async_to_sync")

    @mock.patch("ranking.management.commands.parse_statistic.threading.Timer")
    def test_long_operation_warning_contains_caller_stack(self, timer):
        logger = logging.getLogger("ranking.parse.statistic.test")

        with (
            self.assertLogs(logger, level=logging.WARNING) as logs,
            log_long_operation(logger, "Apply standings", warning_seconds=10, contest_id=123),
        ):
            timer.call_args.args[1]()

        assert "Apply standings is still running after 10 seconds" in logs.output[0]
        assert "contest_id=123" in logs.output[0]
        assert "Caller thread stack:" in logs.output[0]
        assert timer.return_value.daemon is True
        timer.return_value.start.assert_called_once_with()
        timer.return_value.cancel.assert_called_once_with()

    def test_standings_summary_only_contains_allowlisted_metadata(self):
        standings = {
            "result": {"private-user": {"token": "row-secret"}},
            "problems": [{"url": "https://example.com?api_key=problem-secret"}],
            "parsed_percentage": 68.75,
            "action": ("delete", "action-secret"),
            "cookie": "cookie-secret",
        }

        summary = get_standings_log_summary(standings)

        assert summary == "rows=1, problems=1, fields=5, parsed=68.75%, action=delete"
        assert "secret" not in summary
        assert "private-user" not in summary

    def test_unknown_standings_action_is_not_logged_verbatim(self):
        summary = get_standings_log_summary({"action": ["token=action-secret"]})

        assert summary == "rows=0, problems=0, fields=1, action=other"

    def test_parser_modules_use_live_tqdm_adapter(self):
        modules_path = Path(parse_statistic.__file__).parents[1] / "modules"
        direct_imports = []
        for path in modules_path.rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(alias.name == "tqdm" for alias in node.names):
                    direct_imports.append(str(path.relative_to(modules_path)))
                if isinstance(node, ast.ImportFrom) and node.module == "tqdm":
                    direct_imports.append(str(path.relative_to(modules_path)))

        assert direct_imports == []


class ParseStatisticConcurrencyTest(TestCase):
    def setUp(self):
        self.resource = Resource(host="concurrent-parser.example", enable=True, url="https://concurrent-parser.example")
        Resource.objects.bulk_create([self.resource])
        Module.objects.create(
            resource=self.resource,
            path="dummy.py",
            max_delay_after_end=timedelta(hours=1),
            delay_on_success=timedelta(minutes=10),
            delay_on_error=timedelta(minutes=10),
        )
        now = timezone.now()
        self.contest = Contest(
            resource=self.resource,
            title="Concurrent parser test",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            duration_in_secs=3600,
            url="https://concurrent-parser.example/contest",
            key="concurrent-parser-test",
            host=self.resource.host,
            parsed_time=now - timedelta(minutes=30),
        )
        Contest.objects.bulk_create([self.contest])

    def run_with_plugin(self, statistic_class, **kwargs):
        plugin = SimpleNamespace(Statistic=statistic_class)
        parse_kwargs = {
            "with_check": False,
            "without_subscriptions": True,
            **kwargs,
        }
        with mock.patch.object(Resource, "plugin", new_callable=mock.PropertyMock, return_value=plugin):
            return Command().parse_statistic(
                Contest.objects.filter(pk=self.contest.pk),
                **parse_kwargs,
            )

    def test_completed_result_does_not_append_applied_name_override(self):
        self.contest.info["additions"] = {
            "Original Name": {"name": "Corrected Name"},
            "manual": {"member": "manual", "name": "Manual row", "place": 3, "solving": 0},
        }
        self.contest.save(update_fields=["info"])

        class Statistic(BaseModule):
            def get_standings(inner_self, **kwargs):
                result = {
                    member: {"member": member, "name": "Original Name", "place": 1, "solving": 1}
                    for member in ("first", "second")
                }
                inner_self.complete_result(result)
                return {"result": result}

        result = self.run_with_plugin(Statistic)

        assert result.status == parse_statistic.EventStatus.COMPLETED
        names = dict(Statistics.objects.filter(contest=self.contest).values_list("account__key", "addition__name"))
        assert names == {"first": "Corrected Name", "second": "Corrected Name", "manual": "Manual row"}

    def test_reparse_preserves_saved_elo_ratings_with_unchanged_standings(self):
        self.check_reparse_preserves_saved_elo_ratings()

    def test_reparse_preserves_saved_member_elo_ratings_and_fields(self):
        self.check_reparse_preserves_saved_elo_ratings(account_type="member")

    def test_reparse_restores_missing_elo_rating_additions(self):
        self.check_reparse_preserves_saved_elo_ratings(clear_rating_additions=True)

    def check_reparse_preserves_saved_elo_ratings(self, account_type=None, clear_rating_additions=False):
        Resource.objects.filter(pk=self.resource.pk).update(
            rating_prediction=test_calculate_rating_prediction.EloMmrRatingPredictionTest.rating_prediction(
                account_type=account_type
            )
        )
        places = {"first": 1, "second": 2}
        custom_field = "initial"

        class Statistic(BaseModule):
            def get_standings(inner_self, **kwargs):
                result = {
                    member: {
                        "member": member,
                        "place": place,
                        "solving": 3 - place,
                        "custom_field": custom_field,
                        "info": {"is_member": account_type == "member"},
                    }
                    for member, place in places.items()
                }
                options = {"fixed_fields": ["solving"]}
                if account_type == "member":
                    result["user"] = {"member": "user", "place": 3, "solving": 0}
                    options = {"account_type_fields": {"member": options}}
                return {"result": result, "options": options}

        previous_hash = None
        previous_timing = None
        expected_ratings = None
        with mock.patch.object(Resource, "update_icon"):
            for parse_kwargs in ({}, {"with_stats": False, "without_calculate_rating_prediction": True}, {}):
                if clear_rating_additions and expected_ratings:
                    for statistic in Statistics.objects.filter(contest=self.contest):
                        for field in ELO_MMR_RATING_FIELDS:
                            statistic.addition.pop(field, None)
                        statistic.save(update_fields=["addition"])

                result = self.run_with_plugin(Statistic, without_calculate_problem_rating=True, **parse_kwargs)
                assert result.status == parse_statistic.EventStatus.COMPLETED
                self.contest.refresh_from_db()
                ratings = {}
                for statistic in Statistics.objects.filter(contest=self.contest).select_related("account"):
                    if statistic.account.key == "user":
                        assert not any(field in statistic.addition for field in ELO_MMR_RATING_FIELDS)
                        continue
                    ratings[statistic.account.key] = {
                        field: statistic.addition[field] for field in ELO_MMR_RATING_FIELDS
                    }
                    assert statistic.account.rating == statistic.addition["new_rating"]
                    assert statistic.addition["custom_field"] == custom_field
                if previous_hash is not None:
                    assert self.contest.rating_prediction_hash == previous_hash
                    assert self.contest.rating_prediction_timing == previous_timing
                    assert ratings == expected_ratings
                previous_hash = self.contest.rating_prediction_hash
                previous_timing = self.contest.rating_prediction_timing
                expected_ratings = ratings
                assert self.contest.is_rated is True
                assert set(ELO_MMR_RATING_FIELDS) <= set(self.contest.info["fields"])
                assert all(self.contest.info["fields_types"][field] == ["int"] for field in ELO_MMR_RATING_FIELDS)
                standings = self.contest.info["standings"]
                if account_type == "member":
                    standings = standings["account_type_fields"]["member"]
                assert set(ELO_MMR_RATING_FIELDS) <= set(standings["fixed_fields"])
                assert "solving" in standings["fixed_fields"]
                custom_field = "updated"

            places.update(first=2, second=1)
            result = self.run_with_plugin(Statistic, without_calculate_problem_rating=True)

        assert result.status == parse_statistic.EventStatus.COMPLETED
        self.contest.refresh_from_db()
        assert self.contest.rating_prediction_hash != previous_hash
        assert self.contest.rating_prediction_timing != previous_timing
        for statistic in Statistics.objects.filter(contest=self.contest).select_related("account"):
            if statistic.account.key == "user":
                continue
            assert statistic.addition["new_rating"] != expected_ratings[statistic.account.key]["new_rating"]
            assert statistic.account.rating == statistic.addition["new_rating"]

    def test_changed_parsed_time_rejects_fetched_standings(self):
        changed_parsed_time = timezone.now()

        class Statistic(BaseModule):
            def get_standings(inner_self, **kwargs):
                Contest.objects.filter(pk=inner_self.contest.pk).update(parsed_time=changed_parsed_time)
                return {
                    "result": {
                        "tourist": {
                            "member": "tourist",
                            "place": 1,
                            "solving": 1,
                        }
                    }
                }

        result = self.run_with_plugin(Statistic)

        assert result.status == parse_statistic.EventStatus.WARNING
        event_log = parse_statistic.EventLog.objects.get(name="parse_statistic", object_id=self.contest.pk)
        assert "parsed_time changed" in event_log.error
        self.contest.refresh_from_db()
        assert self.contest.parsed_time == changed_parsed_time
        assert not Statistics.objects.filter(contest=self.contest).exists()

    def test_concurrent_contest_change_is_not_overwritten_after_fetch(self):
        changed_title = "Changed while standings were fetched"

        class Statistic(BaseModule):
            def get_standings(inner_self, **kwargs):
                Contest.objects.filter(pk=inner_self.contest.pk).update(title=changed_title)
                return {
                    "result": {
                        "tourist": {
                            "member": "tourist",
                            "place": 1,
                            "solving": 1,
                        }
                    }
                }

        result = self.run_with_plugin(Statistic)

        assert result.status == parse_statistic.EventStatus.COMPLETED
        self.contest.refresh_from_db()
        assert self.contest.title == changed_title
        assert Statistics.objects.filter(contest=self.contest).exists()

    def test_no_update_results_keeps_live_root_cancelled(self):
        live_event_log = parse_statistic.EventLog.objects.create(
            name="parse_statistic",
            related=self.contest,
            status=parse_statistic.EventStatus.IN_PROGRESS,
            is_live_stream=True,
        )

        class Statistic(BaseModule):
            def get_standings(inner_self, **kwargs):
                return {"result": {}}

        result = self.run_with_plugin(
            Statistic,
            live_event_log=live_event_log,
            no_update_results=True,
        )

        assert result.status == parse_statistic.EventStatus.CANCELLED
        assert result.message == "no_update_results"
        live_event_log.refresh_from_db()
        assert live_event_log.status == parse_statistic.EventStatus.CANCELLED
        assert live_event_log.message == "no_update_results"
