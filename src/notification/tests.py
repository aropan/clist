import os
import re
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from importlib import import_module
from io import StringIO
from multiprocessing import get_context
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call, patch

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils.timezone import now
from filelock import FileLock, Timeout
from telegram.error import BadRequest, ChatMigrated, Forbidden

from clist.models import Contest, Resource
from clist.templatetags.extras import md_url
from notification.management.commands.check_logs import Command as CheckLogsCommand
from notification.management.commands.sendout_tasks import Command
from notification.models import Subscription, Task
from notification.utils import (
    CUSTOM_MESSAGE_PLACEHOLDERS,
    compose_message_by_custom_messages,
    render_custom_message,
)
from ranking.models import Account, Statistics


class UpdateGoogleCalendarsTest(SimpleTestCase):
    def test_removes_unnamed_orphan_events_and_continues_cleanup(self):
        for summary in ({}, {"summary": ""}, {"summary": None}):
            with self.subTest(summary=summary):
                service = Mock()
                with patch.dict("sys.modules", {"legacy.api.google_calendar.common": Mock(service=service)}):
                    command = import_module("notification.management.commands.update_google_calendars")
                    resource = Resource(pk=93, host="atcoder.jp", uid="calendar-id")
                    events = [
                        {"id": "unnamed-event", **summary},
                        {"id": "kept-event", "summary": "Current contest"},
                        {"id": "named-event", "summary": "Old contest"},
                    ]
                    stdout = StringIO()
                    with (
                        patch.object(command.Resource, "get", return_value=[resource]),
                        patch.object(command.Contest, "visible") as contests,
                        patch.object(command, "service", service),
                        patch.object(
                            command, "get_all_calendars", return_value=[{"id": resource.uid, "summary": resource.host}]
                        ),
                        patch.object(command, "get_all_events", return_value=events),
                        redirect_stdout(stdout),
                    ):
                        contests.filter.side_effect = [[], [], [Mock()], []]
                        command.Command().handle(resources=[resource.host], days=8)

                    delete = service.events.return_value.delete
                    assert delete.call_args_list == [
                        call(calendarId=resource.uid, eventId="unnamed-event"),
                        call(calendarId=resource.uid, eventId="named-event"),
                    ]
                    assert delete.return_value.execute.call_count == 2
                    assert "-   unnamed-event" in stdout.getvalue()
                    assert "-   Old contest" in stdout.getvalue()


class CheckLogsTest(SimpleTestCase):
    PHP_WARNING = """<b>highload.fun</b>PHP Warning:  Fetch data = 'HTTP/2 405
date: Sun, 16 Aug 2026 17:25:02 GMT
x-trace-id: first-trace

Method Not Allowed
' in /usr/src/legacy/module/highload.fun/index.php on line 7

Warning: Fetch data = 'HTTP/2 405
date: Sun, 16 Aug 2026 17:25:02 GMT
x-trace-id: first-trace

Method Not Allowed
' in /usr/src/legacy/module/highload.fun/index.php on line 7
"""
    NEWTON_WARNING = """<b>my.newtonschool.co</b>PHP Warning:  json = false in \
/usr/src/legacy/module/my.newtonschool.co/index.php on line 20

Warning: json = false in /usr/src/legacy/module/my.newtonschool.co/index.php on line 20
"""

    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.logfile = os.path.join(self.temp_dir.name, "update.log")
        self.cache = {}
        self.command = CheckLogsCommand()
        self.command._bot = Mock()
        self.now = datetime(2026, 8, 16, 12, tzinfo=UTC)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_log(self, *errors, complete=True, begin="Sun Aug 16 12:00:00 UTC 2026"):
        content = f"BEGIN {begin}\n\n" + "\n".join(errors)
        if complete:
            content += "\n\nEND Sun Aug 16 12:05:00 UTC 2026\n"
        with open(self.logfile, "w") as fo:
            fo.write(content)

    def check_log(self, current_time=None):
        self.command._check(
            self.logfile,
            cache=self.cache,
            key="legacy/update.log",
            extractor=self.command._extract_php_errors,
            require_complete=True,
            current_time=current_time or self.now,
        )

    def get_error_states(self):
        return self.cache["legacy/update.log"]["errors"]

    def test_tracks_each_php_error_and_counts_only_new_occurrences(self):
        self.cache["legacy/update.log"] = "old combined hash"
        self.write_log(self.PHP_WARNING)

        self.check_log()

        [error_state] = self.get_error_states().values()
        assert error_state["count"] == 1
        assert error_state["first_seen"] == self.now.isoformat()
        assert error_state["last_seen"] == self.now.isoformat()
        assert "PHP Warning: Fetch data = 'HTTP/2 405" in error_state["message"]
        self.command._bot.admin_message.assert_called_once()

        second_seen = self.now + timedelta(minutes=1)
        self.check_log(second_seen)

        [error_state] = self.get_error_states().values()
        assert error_state["count"] == 1
        assert error_state["last_seen"] == second_seen.isoformat()
        self.command._bot.admin_message.assert_called_once()

        self.write_log(self.PHP_WARNING, self.PHP_WARNING, self.NEWTON_WARNING)
        third_seen = self.now + timedelta(minutes=2)
        self.check_log(third_seen)

        assert sorted(state["count"] for state in self.get_error_states().values()) == [1, 2]
        assert self.command._bot.admin_message.call_count == 2
        message = self.command._bot.admin_message.call_args.args[0]
        assert "my.newtonschool.co/index.php on line 20" in message
        assert "highload.fun/index.php" not in message

        self.write_log(self.PHP_WARNING, begin="Sun Aug 16 13:00:00 UTC 2026")
        self.check_log(self.now + timedelta(hours=1))

        counts_by_message = {state["message"]: state["count"] for state in self.get_error_states().values()}
        highload_state = next(count for message, count in counts_by_message.items() if "highload.fun" in message)
        assert highload_state == 3
        assert self.command._bot.admin_message.call_count == 2

    def test_skips_incomplete_legacy_log(self):
        self.write_log(self.PHP_WARNING, complete=False)

        self.check_log()

        assert self.cache == {}
        self.command._bot.admin_message.assert_not_called()

    def test_skips_contest_php_warning(self):
        self.write_log("PHP Warning: contest = 123 failed in /usr/src/legacy/index.php on line 7")

        self.check_log()

        assert self.cache == {}
        self.command._bot.admin_message.assert_not_called()

    def test_waits_for_end_in_managed_logs_but_processes_streaming_logs(self):
        regex = r"^.*\bERROR\b.*$"
        with open(self.logfile, "w") as fo:
            fo.write("BEGIN Sun Aug 16 12:00:00 UTC 2026\nERROR managed failure\n")

        self.command._check(
            self.logfile,
            regex=regex,
            cache=self.cache,
            key="manage/example.log",
            current_time=self.now,
        )

        assert self.cache == {}
        self.command._bot.admin_message.assert_not_called()

        with open(self.logfile, "a") as fo:
            fo.write("END Sun Aug 16 12:05:00 UTC 2026\n")

        self.command._check(
            self.logfile,
            regex=regex,
            cache=self.cache,
            key="manage/example.log",
            current_time=self.now,
        )

        assert "manage/example.log" in self.cache
        self.command._bot.admin_message.assert_called_once()

        streaming_log = os.path.join(self.temp_dir.name, "streaming.log")
        with open(streaming_log, "w") as fo:
            fo.write("[2026-08-16 12:00:00] ERROR streaming failure\n")

        self.command._check(
            streaming_log,
            regex=regex,
            cache=self.cache,
            key="rqworker/example.log",
            current_time=self.now,
        )

        assert "rqworker/example.log" in self.cache
        assert self.command._bot.admin_message.call_count == 2

    def test_keeps_missing_error_for_one_day_then_reports_recurrence(self):
        self.write_log(self.PHP_WARNING)
        self.check_log()

        self.write_log()
        self.check_log(self.now + timedelta(hours=23))
        assert len(self.get_error_states()) == 1

        self.check_log(self.now + timedelta(hours=25))
        assert "legacy/update.log" not in self.cache

        self.write_log(self.PHP_WARNING)
        recurrence_time = self.now + timedelta(hours=26)
        self.check_log(recurrence_time)

        [error_state] = self.get_error_states().values()
        assert error_state["count"] == 1
        assert error_state["first_seen"] == recurrence_time.isoformat()
        assert self.command._bot.admin_message.call_count == 2

    def test_normalizes_log_timestamps_in_error_signatures(self):
        first_error = "[2026-08-16 12:00:00] ERROR [worker.run:10] failed"
        second_error = "[2026-08-16 12:01:00] ERROR [worker.run:10] failed"

        assert self.command._error_signature(first_error) == self.command._error_signature(second_error)


class SendoutTasksLockTest(SimpleTestCase):
    def run_in_child(self, command):
        context = get_context("fork")
        reader, writer = context.Pipe(duplex=False)

        def run():
            try:
                command.handle()
                writer.send("processed")
            except Timeout:
                writer.send("locked")
            except Exception as error:
                writer.send(repr(error))
            finally:
                writer.close()

        process = context.Process(target=run)
        try:
            process.start()
            writer.close()
            assert reader.poll(10), "Sendout child did not finish"
            result = reader.recv()
            process.join(10)
            assert process.exitcode == 0
            return result
        finally:
            if process.is_alive():
                process.terminate()
                process.join(10)
            reader.close()

    def test_imported_command_can_run_after_fork(self):
        with (
            TemporaryDirectory() as directory,
            patch(
                "notification.management.commands.sendout_tasks.FileLock",
                side_effect=lambda _: FileLock(f"{directory}/sendout.lock", timeout=0),
            ),
            patch.object(Command, "_handle"),
        ):
            command = Command()
            command.handle()
            assert self.run_in_child(command) == "processed"

    def test_forked_command_still_respects_another_process_lock(self):
        with (
            TemporaryDirectory() as directory,
            patch(
                "notification.management.commands.sendout_tasks.FileLock",
                side_effect=lambda _: FileLock(f"{directory}/sendout.lock", timeout=0),
            ),
            patch.object(Command, "_handle"),
            FileLock(f"{directory}/sendout.lock"),
        ):
            assert self.run_in_child(Command()) == "locked"


class SendoutTasksCleanupTest(TestCase):
    def test_cleanup_does_not_evaluate_notification_prefetches(self):
        subscription = Subscription.objects.create(method=settings.NOTIFICATION_CONF.TELEGRAM)
        task = Task.objects.create(notification=subscription, is_sent=True)
        Task._base_manager.filter(pk=task.pk).update(modified=now() - timedelta(days=2))

        with TemporaryDirectory() as temp_dir, patch.object(Command, "CONFIG_FILE", f"{temp_dir}/config.yaml"):
            call_command("sendout_tasks", "--dryrun")

        assert not Task._base_manager.filter(pk=task.pk).exists()


class TelegramSendoutTest(SimpleTestCase):
    def setUp(self):
        self.command = Command()
        self.command.TELEGRAM_BOT = Mock()
        self.command.get_message = Mock(return_value=("subject", "message", {}))
        self.method = settings.NOTIFICATION_CONF.TELEGRAM

    def test_removes_old_unknown_chat_notification(self):
        notification = Mock()
        notification.delete.return_value = (1, {})
        task = Mock(created=now() - timedelta(hours=1))
        self.command.TELEGRAM_BOT.send_message.side_effect = BadRequest("Chat not found")

        status = self.command.send_message(
            Mock(),
            f"{self.method}:100",
            {},
            task=task,
            notification=notification,
        )

        assert status == "removed"
        notification.delete.assert_called_once_with()

    def test_updates_notification_after_chat_migration(self):
        notification = Mock()
        self.command.TELEGRAM_BOT.send_message.side_effect = ChatMigrated(200)

        self.command.send_message(Mock(), f"{self.method}:100", {}, notification=notification)

        assert notification.method == f"{self.method}:200"
        notification.save.assert_called_once_with()

    def test_deletes_personal_chat_when_bot_is_blocked(self):
        coder = Mock(settings={})
        coder.chat.chat_id = 100
        self.command.TELEGRAM_BOT.send_message.side_effect = Forbidden("Bot was blocked by the user")

        self.command.send_message(coder, self.method, {})

        coder.chat.delete.assert_called_once_with()
        coder.save.assert_not_called()

    def test_marks_other_personal_forbidden_error_as_unauthorized(self):
        coder = Mock(settings={})
        coder.chat.chat_id = 100
        self.command.TELEGRAM_BOT.send_message.side_effect = Forbidden("User is deactivated")

        self.command.send_message(coder, self.method, {})

        assert coder.settings["telegram"]["unauthorized"]
        coder.save.assert_called_once_with()

    def test_saves_each_batch_response(self):
        responses = [Mock(), Mock()]
        responses[0].to_dict.return_value = {"message_id": 1}
        responses[1].to_dict.return_value = {"message_id": 2}
        self.command.TELEGRAM_BOT.send_message.side_effect = responses
        tasks = [Mock(), Mock()]

        for task in tasks:
            self.command.send_message(
                Mock(),
                f"{self.method}:100",
                {},
                task=task,
                notification=Mock(),
            )

        assert [task.response for task in tasks] == [{"message_id": 1}, {"message_id": 2}]
        for task in tasks:
            task.save.assert_called_once_with()


class CustomSubscriptionMessagesTest(TestCase):
    def setUp(self):
        self.resource = Resource.objects.create(
            host="custom-messages.example",
            enable=True,
            url="https://custom-messages.example",
        )
        current_time = now()
        self.contest = Contest.objects.create(
            resource=self.resource,
            title="Spring Challenge",
            start_time=current_time - timedelta(days=2),
            end_time=current_time - timedelta(days=1),
            url="https://custom-messages.example/contest",
            key="spring-challenge",
            host=self.resource.host,
        )
        self.account = Account.objects.create(resource=self.resource, key="player")
        self.statistic = Statistics.objects.create(
            account=self.account,
            contest=self.contest,
            resource=self.resource,
            place="1",
            place_as_int=1,
            solving=1,
        )

    def test_every_placeholder_renders_a_markdown_link(self):
        for name in CUSTOM_MESSAGE_PLACEHOLDERS:
            rendered = render_custom_message(f"{{{name}}}", self.statistic)
            assert re.fullmatch(r"\[[^]]+\]\(https://[^)]+\)", rendered), (name, rendered)

        account_url = md_url(f"/standings/{self.contest.pk}/?find_me={self.statistic.pk}")
        contest_url = md_url(f"/standings/{self.contest.pk}/")
        score_history_url = md_url(f"/score-history/{self.statistic.pk}/")
        assert render_custom_message("{account}", self.statistic) == f"[player]({account_url})"
        assert render_custom_message("{contest}", self.statistic) == f"[Spring Challenge]({contest_url})"
        assert render_custom_message("{score_history}", self.statistic) == f"[score history]({score_history_url})"

    def test_unknown_placeholder_is_kept_as_is(self):
        rendered = render_custom_message("{account} moved to {unknown} league", self.statistic)
        assert rendered.endswith(" moved to {unknown} league")

    def test_subscription_account_name_overrides_account_text(self):
        subscription = Mock()
        subscription.account_name.return_value = "Team Alpha"
        rendered = render_custom_message("{account}", self.statistic, subscription)
        assert rendered.startswith("[Team Alpha](")

    def test_messages_of_one_row_are_joined(self):
        custom_messages = [
            {"type": "league_change", "message": "{account} moved to `Bronze` league"},
            {"type": "best_place", "message": "{account} improved place `2` -> `1`"},
        ]
        message = compose_message_by_custom_messages(statistic=self.statistic, custom_messages=custom_messages)
        assert len(message.split("\n")) == 2
        assert "moved to `Bronze` league" in message
        assert "improved place `2` -> `1`" in message

    def test_message_without_custom_names_matches_general_message(self):
        custom_messages = [{"type": "best_place", "message": "{account} improved place `2` -> `1`"}]
        general_message = compose_message_by_custom_messages(
            statistic=self.statistic,
            custom_messages=custom_messages,
        )
        subscription = Mock(locale="en")
        subscription.account_name.return_value = None
        message = compose_message_by_custom_messages(
            statistic=self.statistic,
            custom_messages=custom_messages,
            subscription=subscription,
            general_message=general_message,
        )
        assert message == general_message
