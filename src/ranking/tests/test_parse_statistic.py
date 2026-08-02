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
from ranking.management.commands.parse_statistic import Command, get_standings_log_summary, log_long_operation
from ranking.management.modules.common import BaseModule
from ranking.models import Module, Statistics


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
