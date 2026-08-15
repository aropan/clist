import io
import logging
import sys
import unittest
from datetime import UTC, datetime
from unittest import mock

from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core.management.commands.test import Command as TestCommand
from django.db import connection
from django.db.models import F
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from rq.job import JobStatus, validate_job_id

from clist.models import Resource
from utils import is_interactive
from utils.chart import make_chart
from utils.db import get_order_by
from utils.rq import get_resource_job_id, is_job_active, is_job_id_active
from utils.strings import split_team_name_and_members
from utils.test_runner import CompactTestResult, CompactTextTestRunner


class IsInteractiveTest(SimpleTestCase):
    def test_buffered_stdout_is_not_interactive(self):
        with mock.patch("sys.stdout", io.StringIO()):
            assert not is_interactive()


class PostgresIContainsTest(SimpleTestCase):
    def test_direct_value_uses_ilike_without_upper(self):
        sql = str(ContentType.objects.filter(app_label__icontains="Utils").query)

        assert '"django_content_type"."app_label"::text ILIKE %Utils%' in sql
        assert "UPPER(" not in sql

    def test_expression_uses_ilike_with_escaped_pattern(self):
        sql = str(ContentType.objects.filter(app_label__icontains=F("model")).query)

        assert '"django_content_type"."app_label"::text ILIKE' in sql
        assert '"django_content_type"."model"' in sql
        assert "UPPER(" not in sql


class GetOrderByTest(SimpleTestCase):
    def test_non_nullable_timestamp_uses_database_default_null_order(self):
        for field in ("created", "modified"):
            with self.subTest(field=field):
                ordering = get_order_by(field, "desc")
                assert ordering.expression.name == field
                assert ordering.descending is True
                assert ordering.nulls_last is None
                sql = str(Resource.objects.order_by(ordering).query)
                assert "DESC NULLS LAST" not in sql

    def test_other_fields_keep_nulls_last(self):
        ordering = get_order_by("rating", "asc")

        assert ordering.expression.name == "rating"
        assert ordering.descending is False
        assert ordering.nulls_last is True

    def test_invalid_order_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "Invalid order: random"):
            get_order_by("created", "random")


class MakeChartTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.content_types = ContentType.objects.bulk_create([
            ContentType(app_label="utils_chart_alpha", model="entry"),
            ContentType(app_label="utils_chart_zulu", model="entry"),
        ])
        cls.started_at = datetime(2026, 1, 1, tzinfo=UTC)
        cls.finished_at = datetime(2026, 1, 2, tzinfo=UTC)
        Session.objects.bulk_create([
            Session(session_key="utils-chart-start", session_data="", expire_date=cls.started_at),
            Session(session_key="utils-chart-finish", session_data="", expire_date=cls.finished_at),
        ])

    @staticmethod
    def assert_bounds_query(queries):
        sql = queries[0]["sql"].upper()
        assert "MIN(" in sql
        assert "MAX(" in sql

    @staticmethod
    def data_queries(queries):
        return [query for query in queries if not query["sql"].lstrip().upper().startswith("EXPLAIN")]

    def test_empty_queryset_uses_one_bounds_query(self):
        logger = mock.Mock()
        queryset = ContentType.objects.filter(app_label="utils_chart_missing")

        with CaptureQueriesContext(connection) as queries:
            context = make_chart(queryset, "id", logger=logger)

        queries = self.data_queries(queries)
        assert len(queries) == 1
        assert context is None
        self.assert_bounds_query(queries)
        logger.warning.assert_called_once_with("Empty histogram, field = id")

    def test_numeric_chart_uses_one_bounds_query_before_histogram(self):
        queryset = ContentType.objects.filter(app_label__startswith="utils_chart_")
        src = min(content_type.pk for content_type in self.content_types)
        dst = max(content_type.pk for content_type in self.content_types)

        with CaptureQueriesContext(connection) as queries:
            context = make_chart(queryset, "id", bins=[src, dst])

        queries = self.data_queries(queries)
        assert len(queries) == 2
        self.assert_bounds_query(queries)
        assert context["x_from"] == src
        assert context["x_to"] == dst
        assert sum(row["value"] for row in context["data"]) == 2

    def test_datetime_chart_preserves_time_bounds(self):
        queryset = Session.objects.filter(session_key__startswith="utils-chart-")

        with CaptureQueriesContext(connection) as queries:
            context = make_chart(queryset, "expire_date", bins=[self.started_at, self.finished_at])

        queries = self.data_queries(queries)
        assert len(queries) == 2
        self.assert_bounds_query(queries)
        assert context["x_type"] == "time"
        assert context["x_from"] == self.started_at.timestamp()
        assert context["x_to"] == self.finished_at.timestamp()
        assert sum(row["value"] for row in context["data"]) == 2

    def test_string_chart_preserves_lexical_bounds(self):
        queryset = ContentType.objects.filter(app_label__startswith="utils_chart_")

        with CaptureQueriesContext(connection) as queries:
            context = make_chart(queryset, "app_label")

        queries = self.data_queries(queries)
        assert len(queries) == 3
        self.assert_bounds_query(queries)
        assert "x_from" not in context
        assert "x_to" not in context
        assert context["bins"] == ["utils_chart_alpha", "utils_chart_zulu", "utils_chart_zulu"]
        assert sum(row["value"] for row in context["data"]) == 2


class CompactTestRunnerTest(SimpleTestCase):
    def test_buffer_is_enabled_by_default_and_can_be_disabled(self):
        parser = TestCommand().create_parser("manage.py", "test")

        assert parser.parse_args([]).buffer is True
        assert parser.parse_args(["--buffer"]).buffer is True
        assert parser.parse_args(["--no-buffer"]).buffer is False

    def run_inner_test(self, test_function, logger):
        runner_output = io.StringIO()
        handler_output = io.StringIO()
        handler = logging.StreamHandler(handler_output)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        self.addCleanup(logger.removeHandler, handler)

        suite = unittest.TestSuite([unittest.FunctionTestCase(test_function)])
        runner = CompactTextTestRunner(
            stream=runner_output,
            verbosity=1,
            buffer=True,
            resultclass=CompactTestResult,
        )
        result = runner.run(suite)
        return result, runner_output.getvalue(), handler_output.getvalue()

    def test_discards_logs_from_successful_test(self):
        logger = logging.getLogger(f"{__name__}.successful")

        def successful_test():
            logger.warning("successful test log")

        result, runner_output, handler_output = self.run_inner_test(successful_test, logger)

        assert result.wasSuccessful()
        assert "successful test log" not in runner_output
        assert "successful test log" not in handler_output

    def test_failure_contains_bounded_output_context(self):
        logger = logging.getLogger(f"{__name__}.failed")

        def failed_test():
            for index in range(100):
                logger.warning("log line %03d %s", index, "x" * 1000)
            print("2026-08-03 15:11:46 [cache] https://example.com", file=sys.stderr)
            raise AssertionError("expected failure")

        result, runner_output, handler_output = self.run_inner_test(failed_test, logger)

        assert not result.wasSuccessful()
        assert "AssertionError: expected failure" in runner_output
        assert "Captured stderr (tail):" in runner_output
        assert "log line 099" in runner_output
        assert "log line 000" not in runner_output
        assert "character(s) omitted" in runner_output
        assert "1 cache line(s) omitted" in runner_output
        assert "https://example.com" not in runner_output
        assert len(runner_output) < 25000
        assert not handler_output


class GetResourceJobIdTest(SimpleTestCase):
    def test_dotted_host_is_valid_job_id(self):
        job_id = get_resource_job_id("parse_statistics", "codeforces.com")
        validate_job_id(job_id)
        assert job_id == "parse_statistics_codeforces-com"

    def test_host_with_path_is_valid_job_id(self):
        job_id = get_resource_job_id("parse_accounts", "nerc.itmo.ru/school")
        validate_job_id(job_id)
        assert job_id == "parse_accounts_nerc-itmo-ru-school"


class IsJobActiveTest(SimpleTestCase):
    def setUp(self):
        self.queue = mock.Mock()
        self.queue.started_job_registry.get_job_ids.return_value = []

    @mock.patch("utils.rq.Worker.all")
    def test_active_job_hash_is_enough(self, workers):
        job = mock.Mock()
        job.get_status.return_value = JobStatus.STARTED

        assert is_job_active(self.queue, "parse_statistics_example-com", job)
        job.get_status.assert_called_once_with(refresh=False)
        self.queue.started_job_registry.get_job_ids.assert_not_called()
        workers.assert_not_called()

    @mock.patch("utils.rq.Worker.all", return_value=[])
    def test_terminal_job_hash_is_not_active(self, workers):
        for status in (JobStatus.STOPPED, JobStatus.CANCELED):
            with self.subTest(status=status):
                job = mock.Mock()
                job.get_status.return_value = status

                assert not is_job_active(self.queue, "parse_statistics_example-com", job)

        assert self.queue.started_job_registry.get_job_ids.call_count == 2
        assert workers.call_count == 2

    @mock.patch("utils.rq.Worker.all")
    def test_started_execution_keeps_missing_job_active(self, workers):
        self.queue.started_job_registry.get_job_ids.return_value = ["parse_statistics_example-com"]

        assert is_job_active(self.queue, "parse_statistics_example-com", job=None)
        self.queue.started_job_registry.get_job_ids.assert_called_once_with(cleanup=False)
        workers.assert_not_called()

    @mock.patch("utils.rq.Worker.all")
    def test_worker_keeps_missing_job_active(self, workers):
        worker = mock.Mock()
        worker.get_current_job_id.return_value = "parse_statistics_example-com"
        workers.return_value = [worker]

        assert is_job_active(self.queue, "parse_statistics_example-com", job=None)
        workers.assert_called_once_with(queue=self.queue)

    @mock.patch("utils.rq.Worker.all", return_value=[])
    def test_missing_job_without_execution_or_worker_is_inactive(self, workers):
        assert not is_job_active(self.queue, "parse_statistics_example-com", job=None)
        workers.assert_called_once_with(queue=self.queue)


class IsJobIdActiveTest(SimpleTestCase):
    @mock.patch("utils.rq.is_job_active", return_value=True)
    @mock.patch("utils.rq.django_rq.get_queue")
    def test_uses_job_origin_queue(self, get_queue, is_active):
        system_queue = mock.Mock()
        parse_queue = mock.Mock()
        job = mock.Mock(origin="parse_statistics")
        system_queue.fetch_job.return_value = job
        get_queue.side_effect = lambda name: {
            "system": system_queue,
            "default": mock.Mock(),
            "parse_statistics": parse_queue,
            "parse_accounts": mock.Mock(),
        }[name]

        assert is_job_id_active("job-id")
        is_active.assert_called_once_with(parse_queue, "job-id", job)

    @mock.patch("utils.rq.is_job_active", side_effect=[False, True])
    @mock.patch("utils.rq.django_rq.get_queue")
    def test_checks_registries_when_job_hash_is_missing(self, get_queue, is_active):
        queues = {name: mock.Mock() for name in ("system", "default", "parse_statistics", "parse_accounts")}
        for queue in queues.values():
            queue.fetch_job.return_value = None
        get_queue.side_effect = queues.__getitem__

        assert is_job_id_active("missing-job-id")
        assert is_active.call_args_list == [
            mock.call(queues["system"], "missing-job-id", job=None),
            mock.call(queues["default"], "missing-job-id", job=None),
        ]


class SplitTeamNameAndMembersTest(SimpleTestCase):
    def test_splits_plain_members(self):
        assert split_team_name_and_members("Team (Alice, Bob)") == ("Team", ["Alice", "Bob"])

    def test_allows_one_level_parentheses_in_members(self):
        assert split_team_name_and_members("Team (Alice (coach), Bob)") == ("Team", ["Alice (coach)", "Bob"])

    def test_uses_last_parenthesized_group(self):
        assert split_team_name_and_members("Team (old) (Alice, Bob)") == ("Team (old)", ["Alice", "Bob"])

    def test_rejects_nested_parentheses_in_members(self):
        assert split_team_name_and_members("Team (((Alice)))") is None

    def test_rejects_missing_members_group(self):
        assert split_team_name_and_members("Team") is None

    def test_allows_trailing_whitespace(self):
        assert split_team_name_and_members("Team (Alice, Bob)  ") == ("Team", ["Alice", "Bob"])

    def test_does_not_split_commas_inside_member_parentheses(self):
        assert split_team_name_and_members("Team (Alice (coach, captain), Bob)") == (
            "Team",
            ["Alice (coach, captain)", "Bob"],
        )

    def test_returns_no_members_for_empty_parentheses(self):
        assert split_team_name_and_members("Team ()") == ("Team", [])
