import json
from io import StringIO
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase
from django.test.utils import override_settings
from django.urls import reverse
from telegram import Bot as TelegramBot
from telegram.error import BadRequest
from telegram.request import BaseRequest

from tg.bot import Bot
from tg.transport import TelegramTransport


class FakeTelegramClient:
    instances: ClassVar[list] = []

    def __init__(self, token):
        self.token = token
        self.initialized = 0
        self.shutdowns = 0
        self.calls = []
        self.instances.append(self)

    async def initialize(self):
        self.initialized += 1

    async def shutdown(self):
        self.shutdowns += 1

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs


class FakeTelegramRequest(BaseRequest):
    def __init__(self):
        self.calls = []
        self.initialized = 0
        self.shutdowns = 0

    @property
    def read_timeout(self):
        return None

    async def initialize(self):
        self.initialized += 1

    async def shutdown(self):
        self.shutdowns += 1

    async def do_request(self, url, method, request_data=None, **kwargs):
        api_method = url.rsplit("/", 1)[-1]
        parameters = request_data.parameters if request_data is not None else {}
        self.calls.append((api_method, parameters))
        if api_method == "getMe":
            result = {"id": 1, "is_bot": True, "first_name": "Test", "username": "test_bot"}
        elif api_method == "sendMessage":
            result = {
                "message_id": len(self.calls),
                "date": 0,
                "chat": {"id": parameters["chat_id"], "type": "private"},
                "text": parameters["text"],
            }
        else:
            raise AssertionError(f"unexpected Telegram API method: {api_method}")
        return 200, json.dumps({"ok": True, "result": result}).encode()


class TelegramTransportTest(SimpleTestCase):
    def setUp(self):
        FakeTelegramClient.instances.clear()
        self.transport = TelegramTransport(lambda: "123456:test-token", client_factory=FakeTelegramClient)

    def tearDown(self):
        self.transport.close()

    def test_reuses_initialized_client(self):
        first = self.transport.request("send_message", chat_id="1", text="first")
        second = self.transport.request("send_message", chat_id="1", text="second")

        assert first["text"] == "first"
        assert second["text"] == "second"
        assert len(FakeTelegramClient.instances) == 1
        assert FakeTelegramClient.instances[0].initialized == 1

        client = FakeTelegramClient.instances[0]
        self.transport.close()
        assert client.shutdowns == 1

    def test_real_ptb_bot_uses_fake_request_for_batch(self):
        request = FakeTelegramRequest()
        transport = TelegramTransport(
            lambda: "123456:test-token",
            client_factory=lambda token: TelegramBot(token=token, request=request),
        )
        self.addCleanup(transport.close)

        first = transport.request("send_message", chat_id=100, text="first")
        second = transport.request("send_message", chat_id=100, text="second")

        assert first.text == "first"
        assert second.text == "second"
        assert [method for method, _ in request.calls] == ["getMe", "sendMessage", "sendMessage"]
        assert request.initialized == 1

        transport.close()
        assert request.shutdowns == 1


class TelegramLoggingTest(SimpleTestCase):
    def test_http_clients_do_not_log_request_urls_below_warning(self):
        assert settings.LOGGING["loggers"]["httpx"]["level"] == "WARNING"
        assert settings.LOGGING["loggers"]["httpcore"]["level"] == "WARNING"


class BotTransportTest(SimpleTestCase):
    def test_retries_message_without_markdown(self):
        sent = Mock()
        transport = Mock()
        transport.request.side_effect = [BadRequest("Can't parse entities"), sent]
        bot = Bot(transport=transport)
        bot.from_id = "42"

        response = bot.send_message("broken _markdown", reply_markup=False)

        assert response is sent
        first_call, second_call = transport.request.call_args_list
        assert first_call.args == ("send_message",)
        assert first_call.kwargs["parse_mode"] == "Markdown"
        assert "parse_mode" not in second_call.kwargs

    def test_maps_thread_id_to_message_thread(self):
        transport = Mock()
        bot = Bot(transport=transport)
        bot.from_id = "42"

        bot.send_message("topic", chat_id="100:7", reply_markup=False)

        call = transport.request.call_args
        assert call.args == ("send_message",)
        assert call.kwargs["chat_id"] == "100"
        assert call.kwargs["message_thread_id"] == 7

    def test_maps_webhook_and_topic_methods(self):
        transport = Mock()
        bot = Bot(transport=transport)

        bot.get_webhook_info()
        bot.webhook()
        bot.unwebhook()
        bot.create_topic("100", "Finals")
        bot.delete_topic("100", 7)

        assert transport.request.call_args_list == [
            (("get_webhook_info",), {}),
            (("set_webhook",), {"url": settings.HTTPS_HOST_URL_ + reverse("telegram:incoming")}),
            (("delete_webhook",), {}),
            (("create_forum_topic",), {"chat_id": "100", "name": "Finals"}),
            (("delete_forum_topic",), {"chat_id": "100", "message_thread_id": 7}),
        ]


class TelegramWebhookCommandTest(SimpleTestCase):
    @override_settings(TELEGRAM_TOKEN="123456:test-token")
    @patch("tg.management.commands.ensure_telegram_webhook.Bot")
    def test_updates_missing_webhook(self, bot_class):
        bot = bot_class.return_value
        bot.webhook_url = "https://example.com/telegram/incoming/secret/"
        bot.get_webhook_info.return_value = SimpleNamespace(url="")
        stdout = StringIO()

        call_command("ensure_telegram_webhook", stdout=stdout)

        bot.webhook.assert_called_once_with()
        assert "Telegram webhook updated" in stdout.getvalue()

    @override_settings(TELEGRAM_TOKEN="123456:test-token")
    @patch("tg.management.commands.ensure_telegram_webhook.Bot")
    def test_keeps_current_webhook(self, bot_class):
        bot = bot_class.return_value
        bot.webhook_url = "https://example.com/telegram/incoming/secret/"
        bot.get_webhook_info.return_value = SimpleNamespace(url=bot.webhook_url)
        stdout = StringIO()

        call_command("ensure_telegram_webhook", stdout=stdout)

        bot.webhook.assert_not_called()
        assert "already configured" in stdout.getvalue()

    @override_settings(TELEGRAM_TOKEN=None)
    @patch("tg.management.commands.ensure_telegram_webhook.Bot")
    def test_skips_disabled_telegram(self, bot_class):
        stdout = StringIO()

        call_command("ensure_telegram_webhook", stdout=stdout)

        bot_class.assert_not_called()
        assert "Telegram is disabled" in stdout.getvalue()
