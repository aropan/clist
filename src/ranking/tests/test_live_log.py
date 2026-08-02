from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from clist.models import Contest, Resource
from logify.models import EventLog, EventStatus
from logify.rq import fail_live_event_logs, interrupt_live_event_logs
from ranking.management.modules.common import LOG
from ranking.models import Account, Module
from true_coders.models import Coder


class LiveLogFixtureTest(TestCase):
    def setUp(self):
        self.resource = Resource(host="live-parser.example", enable=True, url="https://live-parser.example")
        Resource.objects.bulk_create([self.resource])
        Module.objects.create(
            resource=self.resource,
            path="dummy.py",
            max_delay_after_end=timedelta(hours=1),
            delay_on_error=timedelta(minutes=10),
        )
        now = timezone.now()
        self.contest = Contest(
            resource=self.resource,
            title="Live parser test",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            duration_in_secs=3600,
            url="https://live-parser.example/contest",
            key="live-parser-test",
            host=self.resource.host,
        )
        Contest.objects.bulk_create([self.contest])

    def run_parse_command(self, *, warning=False, error=None, by_resource=False, users=None):
        session = mock.Mock()
        session_context = mock.MagicMock()
        session_context.__enter__.return_value = session

        def parse_statistic(command, **kwargs):
            if error is not None:
                raise error
            from ranking.management.commands.parse_statistic import ParseStatisticResult

            status = EventStatus.WARNING if warning else EventStatus.COMPLETED
            live_event_log = kwargs["live_event_log"]
            message = "Number of parsed contests: 1 of 1" if live_event_log.related_is(Resource) else None
            result = ParseStatisticResult(
                count=1,
                total=1,
                status=status,
                message=message,
            )
            live_event_log.update(status=result.status, message=result.message)
            if kwargs["specific_users"]:
                live_event_log.delete()
            return result

        patches = (
            mock.patch(
                "ranking.management.commands.parse_statistic.Command.parse_statistic",
                autospec=True,
                side_effect=parse_statistic,
            ),
            mock.patch(
                "ranking.management.commands.parse_statistic.LiveLogSession",
                return_value=session_context,
            ),
        )
        with patches[0], patches[1]:
            command_options = {"resources": [self.resource.host]} if by_resource else {"contest_id": self.contest.pk}
            if users is not None:
                command_options["users"] = users
            if error is None:
                call_command("parse_statistic", **command_options)
            else:
                with pytest.raises(type(error)):
                    call_command("parse_statistic", **command_options)
        return session


class ParseStatisticLiveLifecycleTest(LiveLogFixtureTest):
    def test_successful_run_completes_root_event_log(self):
        session = self.run_parse_command()

        event_log = EventLog.objects.get(name="parse_statistic", object_id=self.contest.pk, is_live_stream=True)
        event_log.refresh_from_db()
        assert event_log.status == EventStatus.COMPLETED
        assert event_log.message is None
        session.add_logger.assert_any_call(LOG)
        session.status.assert_any_call(EventStatus.IN_PROGRESS)
        session.status.assert_any_call(EventStatus.COMPLETED, None)

    def test_partial_errors_mark_root_event_log_as_warning(self):
        session = self.run_parse_command(warning=True)

        event_log = EventLog.objects.get(name="parse_statistic", object_id=self.contest.pk, is_live_stream=True)
        event_log.refresh_from_db()
        assert event_log.status == EventStatus.WARNING
        assert event_log.message is None
        session.status.assert_any_call(EventStatus.WARNING, None)

    def test_uncaught_error_marks_root_event_log_as_failed(self):
        session = self.run_parse_command(error=RuntimeError("parser failed"))

        event_log = EventLog.objects.get(name="parse_statistic", object_id=self.contest.pk, is_live_stream=True)
        event_log.refresh_from_db()
        assert event_log.status == EventStatus.FAILED
        assert event_log.error == "parser failed"
        session.status.assert_any_call(EventStatus.FAILED, "parser failed")

    def test_direct_single_contest_command_creates_live_root(self):
        self.run_parse_command()

        event_log = EventLog.objects.get(name="parse_statistic", object_id=self.contest.pk, is_live_stream=True)
        assert event_log.status == EventStatus.COMPLETED

    def test_resource_root_keeps_final_summary(self):
        session = self.run_parse_command(warning=True, by_resource=True)

        event_log = EventLog.objects.get(name="parse_statistic", is_live_stream=True)
        assert event_log.related == self.resource
        assert event_log.status == EventStatus.WARNING
        assert event_log.message == "Number of parsed contests: 1 of 1"
        session.status.assert_any_call(EventStatus.WARNING, event_log.message)

    def test_specific_users_run_deletes_contest_live_root(self):
        self.run_parse_command(users=["tourist"])

        assert not EventLog.objects.filter(name="parse_statistic", is_live_stream=True).exists()

    @mock.patch("ranking.management.commands.parse_statistic.get_current_job")
    def test_worker_reuses_queued_live_root(self, get_current_job):
        get_current_job.return_value = SimpleNamespace(id="queued-live-job")
        queued_event_log = EventLog.objects.create(
            name="parse_statistic",
            related=self.contest,
            status=EventStatus.NONE,
            message="Update queued. Waiting for the worker to start...",
            job_id="queued-live-job",
            is_live_stream=True,
        )

        self.run_parse_command()

        assert EventLog.objects.filter(name="parse_statistic", is_live_stream=True).count() == 1
        queued_event_log.refresh_from_db()
        assert queued_event_log.status == EventStatus.COMPLETED
        assert queued_event_log.message == ""

    @mock.patch("logify.models.get_current_job")
    @mock.patch("ranking.management.commands.parse_statistic.get_current_job")
    def test_worker_does_not_reuse_terminal_live_root(self, get_current_job, model_get_current_job):
        current_job = SimpleNamespace(id="repeated-resource-job")
        get_current_job.return_value = current_job
        model_get_current_job.return_value = current_job
        completed_event_log = EventLog.objects.create(
            name="parse_statistic",
            related=self.resource,
            status=EventStatus.COMPLETED,
            job_id=current_job.id,
            is_live_stream=True,
        )

        self.run_parse_command(by_resource=True)

        event_logs = EventLog.objects.filter(name="parse_statistic", is_live_stream=True).order_by("created")
        assert event_logs.count() == 2
        completed_event_log.refresh_from_db()
        assert completed_event_log.status == EventStatus.COMPLETED
        new_event_log = event_logs.exclude(pk=completed_event_log.pk).get()
        assert new_event_log.status == EventStatus.COMPLETED
        assert new_event_log.job_id == current_job.id


class ParseStatisticResultTest(LiveLogFixtureTest):
    def test_result_does_not_use_command_instance_state(self):
        from ranking.management.commands.parse_statistic import Command, ParseStatisticResult

        command = Command()
        result = command.parse_statistic(Contest.objects.none())

        assert result == ParseStatisticResult(
            count=0,
            total=0,
            status=EventStatus.COMPLETED,
            message="Number of parsed contests: 0 of 0",
        )
        assert not hasattr(command, "has_parse_warnings")

    def test_partial_error_is_returned_as_warning(self):
        from ranking.management.commands.parse_statistic import Command

        Module.objects.filter(resource=self.resource).delete()

        result = Command().parse_statistic(Contest.objects.filter(pk=self.contest.pk), with_check=False)

        assert result.status == EventStatus.WARNING

    def test_live_contest_root_replaces_per_contest_event_log(self):
        from ranking.management.commands.parse_statistic import Command

        event_log = EventLog.objects.create(
            name="parse_statistic",
            related=self.contest,
            status=EventStatus.IN_PROGRESS,
            is_live_stream=True,
        )

        result = Command().parse_statistic(
            Contest.objects.filter(pk=self.contest.pk),
            with_check=False,
            live_event_log=event_log,
        )

        assert result.status == EventStatus.WARNING
        assert result.message is None
        assert EventLog.objects.filter(name="parse_statistic", object_id=self.contest.pk).count() == 1
        event_log.refresh_from_db()
        assert event_log.status == EventStatus.WARNING
        assert event_log.error == "No module named 'dummy'"

    def test_specific_users_delete_live_contest_event_log(self):
        from ranking.management.commands.parse_statistic import Command

        event_log = EventLog.objects.create(
            name="parse_statistic",
            related=self.contest,
            status=EventStatus.IN_PROGRESS,
            is_live_stream=True,
        )
        event_log_id = event_log.pk

        Command().parse_statistic(
            Contest.objects.filter(pk=self.contest.pk),
            with_check=False,
            specific_users=["tourist"],
            live_event_log=event_log,
        )

        assert not EventLog.objects.filter(pk=event_log_id).exists()


class SplitByResourceLiveLogTest(LiveLogFixtureTest):
    @mock.patch("ranking.management.commands.parse_statistic.is_job_active", return_value=False)
    @mock.patch("ranking.management.commands.parse_statistic.django_rq.get_queue")
    def test_worker_creates_live_event_log_after_enqueue(self, get_queue, is_job_active):
        queue = get_queue.return_value
        queue.fetch_job.return_value = None
        queue.enqueue.return_value = SimpleNamespace(id="parse_statistics_live-parser-example")

        from ranking.management.commands.parse_statistic import Command

        Command().parse_statistic(
            contests=Contest.objects.filter(pk=self.contest.pk),
            split_by_resource=True,
        )

        assert not EventLog.objects.filter(name="parse_statistic", is_live_stream=True).exists()
        queue.enqueue.assert_called_once_with(
            call_command,
            "parse_statistic",
            resources=[self.resource.host],
            job_id="parse_statistics_live-parser-example",
            on_failure=fail_live_event_logs,
            on_stopped=interrupt_live_event_logs,
        )

    @mock.patch("ranking.management.commands.parse_accounts_infos.is_job_active", return_value=False)
    @mock.patch("ranking.management.commands.parse_accounts_infos.django_rq.get_queue")
    def test_parse_accounts_job_has_terminal_callbacks(self, get_queue, is_job_active):
        Resource.objects.filter(pk=self.resource.pk).update(has_accounts_infos_update=True)
        Account.objects.bulk_create([
            Account(
                resource=self.resource,
                key="tourist",
                updated=timezone.now() - timedelta(hours=1),
            )
        ])
        queue = get_queue.return_value
        queue.fetch_job.return_value = None
        queue.enqueue.return_value = SimpleNamespace(id="parse_accounts_live-parser-example")

        call_command("parse_accounts_infos", split_by_resource=True)

        queue.enqueue.assert_called_once_with(
            call_command,
            "parse_accounts_infos",
            resources=[self.resource.host],
            job_id="parse_accounts_live-parser-example",
            on_failure=fail_live_event_logs,
            on_stopped=interrupt_live_event_logs,
        )


class ContestLiveLogEnqueueTest(LiveLogFixtureTest):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_superuser(username="live-log-admin")
        self.coder = Coder.objects.create(user=self.user, username=self.user.username)
        self.client.force_login(self.user)

    @mock.patch("true_coders.views.get_usage", return_value={"should_limit": False})
    @mock.patch("true_coders.views.call_command_parse_statistics.delay")
    @mock.patch("true_coders.views.uuid4", return_value="queued-live-job")
    def test_update_statistics_creates_queued_live_event_log(self, uuid4, delay, get_usage):
        delay.return_value = SimpleNamespace(id="contest-live-job")

        response = self.client.post(
            reverse("coder:change"),
            {
                "pk": self.coder.pk,
                "name": "update-statistics",
                "id": self.contest.pk,
            },
        )

        assert response.status_code == 200
        data = response.json()
        event_log = EventLog.objects.get(name="parse_statistic", is_live_stream=True)
        assert event_log.related == self.contest
        assert event_log.status == EventStatus.NONE
        assert event_log.job_id == "queued-live-job"
        assert event_log.message == "Update queued. Waiting for the worker to start..."
        assert data["job_id"] == "queued-live-job"
        assert data["can_view_live_log"] is True
        assert data["live_logs_data_url"] == reverse("ranking:live_logs_data")
        delay.assert_called_once_with(contest_id=str(self.contest.pk), job_id="queued-live-job")

        live_log_response = self.client.get(data["live_logs_data_url"], {"job_id": data["job_id"]})
        assert live_log_response.status_code == 200
        queued_log = live_log_response.json()["event_logs"][0]
        assert queued_log["status"] == "queued"
        assert queued_log["message"] == "Update queued. Waiting for the worker to start..."

    @mock.patch("true_coders.views.get_usage", return_value={"should_limit": False})
    @mock.patch("true_coders.views.call_command_parse_statistics.delay", side_effect=RuntimeError("Redis is down"))
    @mock.patch("true_coders.views.uuid4", return_value="failed-enqueue-job")
    def test_enqueue_failure_marks_live_event_log_failed(self, uuid4, delay, get_usage):
        with pytest.raises(RuntimeError, match="Redis is down"):
            self.client.post(
                reverse("coder:change"),
                {
                    "pk": self.coder.pk,
                    "name": "update-statistics",
                    "id": self.contest.pk,
                },
            )

        event_log = EventLog.objects.get(job_id="failed-enqueue-job", is_live_stream=True)
        assert event_log.status == EventStatus.FAILED
        assert event_log.message == ""
        assert event_log.error == "Redis is down"


class ParseAccountsInfosLiveLifecycleTest(LiveLogFixtureTest):
    @mock.patch("ranking.management.commands.parse_accounts_infos.LiveLogSession")
    def test_single_resource_worker_creates_live_root(self, live_log_session):
        session = mock.Mock()
        live_log_session.return_value.__enter__.return_value = session
        Resource.objects.filter(pk=self.resource.pk).update(info={"accounts": {"skip": True}})

        call_command("parse_accounts_infos", resources=[self.resource.host])

        event_log = EventLog.objects.get(
            name="parse_accounts_infos",
            object_id=self.resource.pk,
            is_live_stream=True,
        )
        assert event_log.related == self.resource
        assert event_log.status == EventStatus.COMPLETED
        session.add_logger.assert_any_call(LOG)
        session.status.assert_any_call(EventStatus.IN_PROGRESS)
        session.status.assert_any_call(EventStatus.COMPLETED, None)
