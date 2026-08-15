from datetime import timedelta
from unittest.mock import Mock

from django.conf import settings
from django.test import SimpleTestCase
from django.utils.timezone import now
from telegram.error import BadRequest, ChatMigrated, Forbidden

from notification.management.commands.sendout_tasks import Command


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
