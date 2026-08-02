import asyncio
import io
import logging
import threading
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

import pytest
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from guardian.shortcuts import assign_perm

from clist.models import Contest, Resource
from logify.access import (
    can_view_any_live_updates,
    can_view_live_event_log,
    get_active_live_event_logs,
    get_live_event_log_for_contest,
    get_live_event_log_for_job,
)
from logify.live import (
    LIVE_LOG_MESSAGE_LIMIT,
    LiveLogSession,
    get_live_log_history,
    register_live_logger,
    stream_event_log,
    tqdm,
    trange,
)
from logify.models import EventLog, EventStatus
from logify.rq import fail_live_event_logs, interrupt_live_event_logs, interrupt_stale_event_logs
from logify.templatetags.logify import can_view_live_updates
from ranking.models import Stage
from true_coders.models import Coder


class EventLogJobTest(TestCase):
    def setUp(self):
        self.related = User.objects.create_user(username="event-log-job-test")

    @mock.patch("logify.models.get_current_job")
    def test_create_stores_current_job_id(self, get_current_job):
        get_current_job.return_value = SimpleNamespace(id="parse_statistics_example-com")

        event_log = EventLog.objects.create(name="test", related=self.related)

        assert event_log.job_id == "parse_statistics_example-com"

    def test_related_is_checks_related_model(self):
        event_log = EventLog.objects.create(name="test", related=self.related)

        assert event_log.related_is(User)
        assert not event_log.related_is(Resource)

    def test_interrupt_in_progress_only_affects_matching_job(self):
        stale = EventLog.objects.create(
            name="test",
            related=self.related,
            status=EventStatus.IN_PROGRESS,
            job_id="parse_statistics_example-com",
        )
        completed = EventLog.objects.create(
            name="test",
            related=self.related,
            status=EventStatus.COMPLETED,
            job_id="parse_statistics_example-com",
        )
        other_job = EventLog.objects.create(
            name="test",
            related=self.related,
            status=EventStatus.IN_PROGRESS,
            job_id="parse_statistics_other-com",
        )

        n_interrupted = EventLog.env_objects.interrupt_in_progress(
            "parse_statistics_example-com",
            error="RQ job is no longer active",
        )

        assert n_interrupted == 1
        stale.refresh_from_db()
        completed.refresh_from_db()
        other_job.refresh_from_db()
        assert stale.status == EventStatus.INTERRUPTED
        assert stale.error == "RQ job is no longer active"
        assert stale.elapsed is not None
        assert completed.status == EventStatus.COMPLETED
        assert other_job.status == EventStatus.IN_PROGRESS

    def test_interrupt_in_progress_ignores_empty_job_id(self):
        without_job = EventLog.objects.create(
            name="test",
            related=self.related,
            status=EventStatus.IN_PROGRESS,
        )

        n_interrupted = EventLog.env_objects.interrupt_in_progress(
            None,
            error="RQ job is no longer active",
        )

        assert n_interrupted == 0
        without_job.refresh_from_db()
        assert without_job.status == EventStatus.IN_PROGRESS
        assert without_job.error is None
        assert without_job.elapsed is None

    @mock.patch("logify.rq.publish_live_log_status")
    def test_failure_callback_finishes_queued_live_event_log(self, publish_live_log_status):
        event_log = EventLog.objects.create(
            name="test",
            related=self.related,
            status=EventStatus.NONE,
            message="queued",
            job_id="failed-live-job",
            is_live_stream=True,
        )

        fail_live_event_logs(
            SimpleNamespace(id=event_log.job_id),
            connection=None,
            exception_type=RuntimeError,
            exception_value=RuntimeError("worker failed"),
            traceback=None,
        )

        event_log.refresh_from_db()
        assert event_log.status == EventStatus.FAILED
        assert event_log.message == ""
        assert event_log.error == "worker failed"
        publish_live_log_status.assert_called_once_with(event_log.pk, EventStatus.FAILED, "worker failed")

    @mock.patch("logify.rq.publish_live_log_status")
    def test_stopped_callback_finishes_in_progress_live_event_log(self, publish_live_log_status):
        event_log = EventLog.objects.create(
            name="test",
            related=self.related,
            status=EventStatus.IN_PROGRESS,
            job_id="stopped-live-job",
            is_live_stream=True,
        )

        interrupt_live_event_logs(SimpleNamespace(id=event_log.job_id), connection=None)

        event_log.refresh_from_db()
        assert event_log.status == EventStatus.INTERRUPTED
        assert event_log.error == "RQ job stopped"
        publish_live_log_status.assert_called_once_with(event_log.pk, EventStatus.INTERRUPTED, "RQ job stopped")

    @mock.patch("logify.rq.publish_live_log_status")
    def test_stale_job_interrupt_publishes_live_root_status(self, publish_live_log_status):
        live_root = EventLog.objects.create(
            name="test",
            related=self.related,
            status=EventStatus.IN_PROGRESS,
            message="working",
            job_id="stale-live-job",
            is_live_stream=True,
        )
        child = EventLog.objects.create(
            name="test",
            related=self.related,
            status=EventStatus.IN_PROGRESS,
            job_id=live_root.job_id,
        )

        n_interrupted = interrupt_stale_event_logs(live_root.job_id, "RQ job is no longer active")

        assert n_interrupted == 2
        live_root.refresh_from_db()
        child.refresh_from_db()
        assert live_root.status == EventStatus.INTERRUPTED
        assert live_root.message == ""
        assert child.status == EventStatus.INTERRUPTED
        publish_live_log_status.assert_called_once_with(
            live_root.pk,
            EventStatus.INTERRUPTED,
            "RQ job is no longer active",
        )


class FakeChannelLayer:
    def __init__(self):
        self.messages = []
        self.thread_ids = set()
        self.loop_ids = set()
        self.closed = 0

    async def group_send(self, group_name, message):
        self.thread_ids.add(threading.get_ident())
        self.loop_ids.add(id(asyncio.get_running_loop()))
        self.messages.append((group_name, message))

    async def close_pools(self):
        self.closed += 1


class LiveLogSessionTest(SimpleTestCase):
    def test_one_sender_thread_loop_and_channel_layer_are_reused(self):
        channel_layer = FakeChannelLayer()
        factory = mock.Mock(return_value=channel_layer)
        event_log = SimpleNamespace(pk=123)

        with LiveLogSession(
            event_log,
            channel_layer_factory=factory,
            batch_interval=0.001,
        ) as session:
            session.log("INFO", "first")
            session.progress(
                bar_id="bar-1",
                description="items",
                current=1,
                total=2,
                progress=0.5,
                elapsed=1,
                rate=1,
                eta=1,
                completed=False,
            )
            session.status(EventStatus.COMPLETED)

        factory.assert_called_once_with()
        assert len(channel_layer.thread_ids) == 1
        assert threading.get_ident() not in channel_layer.thread_ids
        assert len(channel_layer.loop_ids) == 1
        assert channel_layer.closed == 1
        events = [event for _, message in channel_layer.messages for event in message["events"]]
        assert [event["kind"] for event in events] == ["log", "progress", "status"]
        assert all(group == "LIVE_EVENT_LOG__123" for group, _ in channel_layer.messages)
        assert get_live_log_history(123) == events

    def test_nested_command_logger_can_join_current_session(self):
        channel_layer = FakeChannelLayer()
        nested_logger = logging.getLogger("test.live_log.nested")
        nested_logger.setLevel(logging.INFO)

        with LiveLogSession(
            SimpleNamespace(pk=123),
            channel_layer_factory=lambda: channel_layer,
            batch_interval=0.001,
        ):
            register_live_logger(nested_logger)
            nested_logger.info("nested command message")

        events = [event for _, message in channel_layer.messages for event in message["events"]]
        assert [event["message"] for event in events] == ["nested command message"]
        assert not nested_logger.handlers

    @mock.patch("logify.live.LiveLogSession")
    def test_stream_event_log_completes_in_progress_event(self, live_log_session):
        session = live_log_session.return_value.__enter__.return_value
        event_log = mock.Mock(status=EventStatus.IN_PROGRESS, message="working")
        event_log.update_status.side_effect = lambda status: setattr(event_log, "status", status)

        with stream_event_log(event_log, logging.getLogger("test.live_log.stream")):
            pass

        event_log.update_status.assert_called_once_with(EventStatus.COMPLETED)
        session.status.assert_has_calls([
            mock.call(EventStatus.IN_PROGRESS, "working"),
            mock.call(EventStatus.COMPLETED, "working"),
        ])

    @mock.patch("logify.live.LiveLogSession")
    def test_stream_event_log_marks_unhandled_exception_failed(self, live_log_session):
        session = live_log_session.return_value.__enter__.return_value
        event_log = mock.Mock(status=EventStatus.IN_PROGRESS, message=None)

        def update_event_log(**kwargs):
            for field, value in kwargs.items():
                setattr(event_log, field, value)

        event_log.update.side_effect = update_event_log

        with pytest.raises(RuntimeError, match="boom"), stream_event_log(event_log):
            raise RuntimeError("boom")

        event_log.update.assert_called_once_with(status=EventStatus.FAILED, error="boom")
        session.status.assert_has_calls([
            mock.call(EventStatus.IN_PROGRESS, None),
            mock.call(EventStatus.FAILED, "boom"),
        ])

    def test_overflow_is_non_blocking_and_terminal_status_is_kept(self):
        session = LiveLogSession(SimpleNamespace(pk=1), queue_size=2)

        assert session.log("INFO", "first") is None
        session.log("INFO", "second")
        session.log("INFO", "dropped")
        session.status(EventStatus.COMPLETED)

        assert len(session._events) == 2
        batch = session._next_batch()
        assert batch[-1]["kind"] == "status"
        assert batch[-1]["status"] == EventStatus.COMPLETED
        assert batch[-1]["dropped_before"] == 1

    def test_status_has_server_timestamp(self):
        session = LiveLogSession(SimpleNamespace(pk=1))
        timestamp = 1785587696

        with mock.patch("logify.live.time", return_value=timestamp):
            session.status(EventStatus.IN_PROGRESS, "working")

        assert session._events[0]["timestamp"] == timestamp

    def test_log_timestamp_is_unix_time(self):
        session = LiveLogSession(SimpleNamespace(pk=1))

        session.log("INFO", "working", timestamp=1785587696.75)

        assert session._events[0]["timestamp"] == 1785587696

    def test_log_lines_are_sanitized_and_truncated(self):
        session = LiveLogSession(SimpleNamespace(pk=1))

        session.log("INFO", f"\x1b[31m{'x' * (LIVE_LOG_MESSAGE_LIMIT + 1)}\x1b[0m")

        event = session._events[0]
        assert "\x1b" not in event["message"]
        assert len(event["message"]) == LIVE_LOG_MESSAGE_LIMIT
        assert event["message"].endswith("...")

    def test_secrets_are_redacted_from_every_live_text_event(self):
        session = LiveLogSession(SimpleNamespace(pk=1))

        session.log(
            "WARNING",
            "url=https://user:basic-secret@example.com/api?token=url-secret&page=2, "
            "headers={'Authorization': 'Bearer auth-secret', 'Cookie': 'sid=cookie-secret'}, "
            "params=[('api_key', 'tuple-secret')], password=plain-secret, contest=42",
        )
        session.progress(
            bar_id="bar-1",
            description="fetch https://example.com/page?session_id=progress-secret&page=3",
            current=1,
            total=2,
        )
        session.status(EventStatus.IN_PROGRESS, "oauth_token=status-secret, retrying")

        messages = [session._events[0]["message"], session._events[1]["description"], session._events[2]["message"]]
        assert all("secret" not in message for message in messages)
        assert all("<redacted>" in message for message in messages)
        assert "page=2" in messages[0]
        assert "contest=42" in messages[0]
        assert "page=3" in messages[1]


class LiveTqdmTest(SimpleTestCase):
    def test_without_session_behaves_as_regular_tqdm(self):
        assert list(tqdm([1, 2], disable=True)) == [1, 2]
        assert list(trange(2, disable=True)) == [0, 1]

    def test_progress_is_emitted_only_from_display_and_throttled(self):
        session = mock.Mock()
        session.next_bar_id.return_value = "bar-1"
        with (
            mock.patch("logify.live.get_current_session", return_value=session),
            mock.patch("logify.live.monotonic", return_value=10),
        ):
            progress_bar = tqdm(total=2, file=io.StringIO(), mininterval=0)
            progress_bar.update(1)
            progress_bar.refresh()
            progress_bar.update(1)
            progress_bar.close()

        assert session.progress.call_count == 2
        first, completed = [call.kwargs for call in session.progress.call_args_list]
        assert first["bar_id"] == "bar-1"
        assert first["current"] == 0
        assert completed["current"] == 2
        assert completed["completed"] is True

    def test_session_is_captured_when_bar_is_created(self):
        session = mock.Mock()
        session.next_bar_id.return_value = "bar-1"
        clock = mock.Mock(side_effect=[0] + [1] * 10)
        with (
            mock.patch("logify.live.get_current_session", return_value=session),
            mock.patch("logify.live.monotonic", clock),
        ):
            progress_bar = tqdm(total=2, file=io.StringIO(), mininterval=0)
            session.progress.reset_mock()
            worker = threading.Thread(target=progress_bar.update)
            worker.start()
            worker.join()
            progress_bar.close()

        session.progress.assert_called()
        assert session.progress.call_args.kwargs["bar_id"] == "bar-1"

    def test_nested_bars_have_distinct_ids(self):
        session = mock.Mock()
        session.next_bar_id.side_effect = ["bar-1", "bar-2"]
        with (
            mock.patch("logify.live.get_current_session", return_value=session),
            mock.patch("logify.live.monotonic", return_value=10),
        ):
            first = tqdm(total=1, file=io.StringIO())
            second = tqdm(total=1, file=io.StringIO())
            first.close()
            second.close()

        bar_ids = [call.kwargs["bar_id"] for call in session.progress.call_args_list]
        assert list(dict.fromkeys(bar_ids)) == ["bar-1", "bar-2"]

    def test_expanded_total_emits_a_new_completion(self):
        session = mock.Mock()
        session.next_bar_id.return_value = "bar-1"
        with (
            mock.patch("logify.live.get_current_session", return_value=session),
            mock.patch("logify.live.monotonic", return_value=10),
        ):
            progress_bar = tqdm(total=2, file=io.StringIO(), mininterval=0)
            progress_bar.update(2)
            progress_bar.total = 6
            progress_bar.set_description_str("expanded", refresh=False)
            progress_bar.update(4)
            progress_bar.close()

        completed = [call.kwargs for call in session.progress.call_args_list if call.kwargs["completed"]]
        completed_values = [(event["description"], event["current"], event["total"]) for event in completed]
        assert completed_values == [
            ("", 2, 2),
            ("expanded", 6, 6),
        ], completed_values

    def test_expanded_total_immediately_reopens_completed_progress(self):
        session = mock.Mock()
        session.next_bar_id.return_value = "bar-1"
        with (
            mock.patch("logify.live.get_current_session", return_value=session),
            mock.patch("logify.live.monotonic", return_value=10),
        ):
            progress_bar = tqdm(total=1, file=io.StringIO(), mininterval=0)
            progress_bar.update()
            progress_bar.total += 1
            progress_bar.refresh()
            progress_bar.close()

        event = session.progress.call_args.kwargs
        assert event["current"] == 1
        assert event["total"] == 2
        assert event["completed"] is False

    def test_incomplete_close_finishes_live_progress(self):
        session = mock.Mock()
        session.next_bar_id.return_value = "bar-1"
        with (
            mock.patch("logify.live.get_current_session", return_value=session),
            mock.patch("logify.live.monotonic", return_value=10),
        ):
            progress_bar = tqdm(total=3, file=io.StringIO(), mininterval=0)
            progress_bar.update()
            progress_bar.close()

        event = session.progress.call_args.kwargs
        assert event["current"] == 1
        assert event["total"] == 3
        assert event["completed"] is False
        assert event["finished"] is True

    def test_unknown_total_close_finishes_live_progress(self):
        session = mock.Mock()
        session.next_bar_id.return_value = "bar-1"
        with (
            mock.patch("logify.live.get_current_session", return_value=session),
            mock.patch("logify.live.monotonic", return_value=10),
        ):
            progress_bar = tqdm(file=io.StringIO(), mininterval=0)
            progress_bar.update()
            progress_bar.close()

        event = session.progress.call_args.kwargs
        assert event["current"] == 1
        assert event["total"] is None
        assert event["completed"] is False
        assert event["finished"] is True

    def test_del_is_not_overridden(self):
        assert "__del__" not in tqdm.__dict__


class LiveLogPermissionTest(SimpleTestCase):
    def setUp(self):
        self.user = mock.Mock(is_authenticated=True)
        self.user.has_perm.return_value = False

    def test_global_permission_allows_any_related_object(self):
        self.user.has_perm.side_effect = lambda permission, obj=None: permission == "logify.view_all_live_updates"
        event_log = SimpleNamespace(related=object())

        assert can_view_live_event_log(self.user, event_log)

    def test_resource_object_permission_is_used(self):
        resource = Resource()
        self.user.has_perm.side_effect = lambda permission, obj=None: obj is resource

        assert can_view_live_event_log(self.user, SimpleNamespace(related=resource))

    def test_contest_can_be_allowed_through_its_resource(self):
        resource = Resource()
        contest = Contest(resource=resource)
        self.user.has_perm.side_effect = lambda permission, obj=None: obj is resource

        assert can_view_live_event_log(self.user, SimpleNamespace(related=contest))

    def test_stage_can_be_allowed_through_its_contest(self):
        resource = Resource()
        contest = Contest(resource=resource)
        stage = Stage(contest=contest)
        self.user.has_perm.side_effect = lambda permission, obj=None: obj is contest

        assert can_view_live_event_log(self.user, SimpleNamespace(related=stage))

    def test_unknown_related_object_requires_global_permission(self):
        assert not can_view_live_event_log(self.user, SimpleNamespace(related=object()))


class LiveLogTemplateTagTest(SimpleTestCase):
    def setUp(self):
        cache.delete("live-updates-nav-permission:123")

    @mock.patch("logify.templatetags.logify.can_view_any_live_updates", return_value=True)
    def test_navbar_permission_is_cached_between_renders(self, can_view_any_live_updates):
        user = SimpleNamespace(pk=123, is_authenticated=True)

        assert can_view_live_updates(user)
        assert can_view_live_updates(user)

        can_view_any_live_updates.assert_called_once_with(user)


class LiveLogPermissionDatabaseTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="live-log-permission-test")
        cache.delete(f"live-updates-nav-permission:{self.user.pk}")
        Coder.objects.create(user=self.user, username=self.user.username)
        debug_permission, _ = Permission.objects.get_or_create(
            codename="view_debug",
            content_type=ContentType.objects.get_for_model(User),
            defaults={"name": "Can view debug pages"},
        )
        self.user.user_permissions.add(debug_permission)
        self.resource = Resource(host="live-log.example", enable=True, url="https://live-log.example")
        Resource.objects.bulk_create([self.resource])

    def test_guardian_resource_permission_allows_live_log(self):
        event_log = EventLog.objects.create(
            name="parse_statistic",
            related=self.resource,
            status=EventStatus.IN_PROGRESS,
            is_live_stream=True,
        )
        assign_perm("view_live_updates", self.user, self.resource)

        assert can_view_any_live_updates(self.user)
        assert can_view_live_event_log(self.user, event_log)
        assert list(get_active_live_event_logs(self.user)) == [event_log]

        self.client.force_login(self.user)
        page_response = self.client.get(reverse("ranking:live_logs"))
        assert page_response.status_code == 200, (page_response.status_code, page_response.get("Location"))
        assert reverse("ranking:live_logs") in page_response.content.decode()
        response = self.client.get(reverse("ranking:live_logs_data"))
        assert response.status_code == 200
        assert response.json()["event_logs"][0]["id"] == event_log.pk

    def test_live_logs_page_requires_live_updates_permission(self):
        assert not can_view_any_live_updates(self.user)

        self.client.force_login(self.user)

        assert self.client.get(reverse("ranking:live_logs")).status_code == 403
        assert self.client.get(reverse("ranking:live_logs_data")).status_code == 403

    def test_non_live_and_completed_logs_are_not_listed(self):
        assign_perm("view_live_updates", self.user, self.resource)
        EventLog.objects.create(
            name="parse_statistic",
            related=self.resource,
            status=EventStatus.IN_PROGRESS,
            is_live_stream=None,
        )
        EventLog.objects.create(
            name="parse_statistic",
            related=self.resource,
            status=EventStatus.COMPLETED,
            is_live_stream=True,
        )

        assert list(get_active_live_event_logs(self.user)) == []

    def test_active_log_limit_is_applied_after_permissions(self):
        assign_perm("view_live_updates", self.user, self.resource)
        allowed_event_log = EventLog.objects.create(
            name="parse_statistic",
            related=self.resource,
            status=EventStatus.IN_PROGRESS,
            is_live_stream=True,
        )
        private_resource = Resource(
            host="newer-private-live-log.example",
            enable=True,
            url="https://newer-private-live-log.example",
        )
        Resource.objects.bulk_create([private_resource])
        EventLog.objects.create(
            name="parse_statistic",
            related=private_resource,
            status=EventStatus.IN_PROGRESS,
            is_live_stream=True,
        )

        assert get_active_live_event_logs(self.user, limit=1) == [allowed_event_log]

    def test_completed_live_log_can_be_resolved_by_job_id(self):
        assign_perm("view_live_updates", self.user, self.resource)
        event_log = EventLog.objects.create(
            name="parse_statistic",
            related=self.resource,
            status=EventStatus.COMPLETED,
            job_id="completed-live-job",
            is_live_stream=True,
        )

        assert get_live_event_log_for_job(self.user, event_log.job_id) == event_log

        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("ranking:live_logs_data"), {"job_id": event_log.job_id})
        assert response.status_code == 200
        assert response.json()["event_logs"][0]["id"] == event_log.pk

    def test_contest_lookup_resolves_resource_live_root_through_child_event_log(self):
        now = timezone.now()
        contest = Contest(
            resource=self.resource,
            title="Live resource child",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            duration_in_secs=3600,
            url="https://live-log.example/contest",
            key="live-resource-child",
            host=self.resource.host,
        )
        Contest.objects.bulk_create([contest])
        root_event_log = EventLog.objects.create(
            name="parse_statistic",
            related=self.resource,
            status=EventStatus.IN_PROGRESS,
            job_id="parse-statistic-resource-job",
            is_live_stream=True,
        )
        EventLog.objects.create(
            name="parse_statistic",
            related=contest,
            status=EventStatus.IN_PROGRESS,
            job_id=root_event_log.job_id,
        )
        assign_perm("view_live_updates", self.user, self.resource)

        assert get_live_event_log_for_contest(self.user, contest) == root_event_log

        self.client.force_login(self.user)
        response = self.client.get(reverse("ranking:live_logs_data"), {"contest_id": contest.pk})

        assert response.status_code == 200
        assert response.json()["event_logs"][0]["id"] == root_event_log.pk

    def test_contest_lookup_does_not_cross_resource_permissions(self):
        assign_perm("view_live_updates", self.user, self.resource)
        private_resource = Resource(
            host="private-contest-live-log.example",
            enable=True,
            url="https://private-contest-live-log.example",
        )
        Resource.objects.bulk_create([private_resource])
        now = timezone.now()
        private_contest = Contest(
            resource=private_resource,
            title="Private live resource child",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            duration_in_secs=3600,
            url="https://private-contest-live-log.example/contest",
            key="private-live-resource-child",
            host=private_resource.host,
        )
        Contest.objects.bulk_create([private_contest])
        EventLog.objects.create(
            name="parse_statistic",
            related=private_resource,
            status=EventStatus.IN_PROGRESS,
            job_id="private-parse-statistic-resource-job",
            is_live_stream=True,
        )
        EventLog.objects.create(
            name="parse_statistic",
            related=private_contest,
            status=EventStatus.IN_PROGRESS,
            job_id="private-parse-statistic-resource-job",
        )

        assert get_live_event_log_for_contest(self.user, private_contest) is None

        self.client.force_login(self.user)
        response = self.client.get(reverse("ranking:live_logs_data"), {"contest_id": private_contest.pk})

        assert response.status_code == 200
        assert response.json()["event_logs"] == []

    def test_job_lookup_does_not_cross_resource_permissions(self):
        assign_perm("view_live_updates", self.user, self.resource)
        other_resource = Resource(host="private-live-log.example", enable=True, url="https://private-live-log.example")
        Resource.objects.bulk_create([other_resource])
        EventLog.objects.create(
            name="parse_statistic",
            related=other_resource,
            status=EventStatus.IN_PROGRESS,
            job_id="private-live-job",
            is_live_stream=True,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("ranking:live_logs_data"), {"job_id": "private-live-job"})

        assert response.status_code == 200
        assert response.json()["event_logs"] == []

    def test_global_permission_allows_unknown_related_type(self):
        permission = Permission.objects.get(
            codename="view_all_live_updates",
            content_type__app_label="logify",
        )
        self.user.user_permissions.add(permission)
        event_log = EventLog.objects.create(
            name="other_command",
            related=self.user,
            status=EventStatus.IN_PROGRESS,
            is_live_stream=True,
        )

        assert can_view_any_live_updates(self.user)
        assert can_view_live_event_log(self.user, event_log)

        self.client.force_login(self.user)
        response = self.client.get(reverse("ranking:live_logs"))
        assert response.status_code == 200
        assert reverse("ranking:live_logs") in response.content.decode()
