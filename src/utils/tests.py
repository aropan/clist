import io
import logging
import sys
import unittest
from unittest import mock

from django.core.management.commands.test import Command as TestCommand
from django.test import SimpleTestCase
from rq.job import JobStatus, validate_job_id

from utils import is_interactive
from utils.rq import get_resource_job_id, is_job_active
from utils.strings import split_team_name_and_members
from utils.test_runner import CompactTestResult, CompactTextTestRunner


class IsInteractiveTest(SimpleTestCase):
    def test_buffered_stdout_is_not_interactive(self):
        with mock.patch("sys.stdout", io.StringIO()):
            assert not is_interactive()


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
