from unittest import mock

from django.test import SimpleTestCase
from rq.job import JobStatus, validate_job_id

from utils.rq import get_resource_job_id, is_job_active
from utils.strings import split_team_name_and_members


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
