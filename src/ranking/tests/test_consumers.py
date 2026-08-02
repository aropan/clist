from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from guardian.shortcuts import assign_perm

from clist.models import Contest, Resource
from logify.event_status import EventStatus
from logify.live import append_live_log_history, clear_live_log_history, get_live_log_group_name
from logify.models import EventLog
from ranking.consumers import LiveLogConsumer


class WebSocketOriginTest(TransactionTestCase):
    def setUp(self):
        resource = Resource(host="origin-test.example", enable=True, url="https://origin-test.example")
        Resource.objects.bulk_create([resource])
        now = timezone.now()
        self.contest = Contest(
            resource=resource,
            title="WebSocket origin test",
            start_time=now - timedelta(hours=1),
            end_time=now,
            duration_in_secs=3600,
            url="https://origin-test.example/contest",
            key="origin-test",
            host=resource.host,
        )
        Contest.objects.bulk_create([self.contest])

    @override_settings(WEBSOCKET_ALLOWED_ORIGINS=["https://clist.by"])
    def test_foreign_origin_is_rejected(self):
        from pyclist.asgi import get_application

        async def connect():
            communicator = WebsocketCommunicator(
                get_application(),
                f"/ws/contest/?pk={self.contest.pk}",
                headers=[(b"origin", b"https://evil.example")],
            )
            connected, _ = await communicator.connect()
            return connected

        assert not async_to_sync(connect)()

    @override_settings(WEBSOCKET_ALLOWED_ORIGINS=["https://clist.by"])
    def test_allowed_origin_connects(self):
        from pyclist.asgi import get_application

        async def connect():
            communicator = WebsocketCommunicator(
                get_application(),
                f"/ws/contest/?pk={self.contest.pk}",
                headers=[(b"origin", b"https://clist.by")],
            )
            connected, _ = await communicator.connect()
            if connected:
                await communicator.disconnect()
            return connected

        assert async_to_sync(connect)()


class LiveLogConsumerPermissionTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="live-log-consumer")
        self.allowed_resource = Resource(
            host="allowed-live-log.example",
            enable=True,
            url="https://allowed-live-log.example",
        )
        self.private_resource = Resource(
            host="private-live-log.example",
            enable=True,
            url="https://private-live-log.example",
        )
        Resource.objects.bulk_create([self.allowed_resource, self.private_resource])
        assign_perm("view_live_updates", self.user, self.allowed_resource)
        self.allowed_event_log = EventLog.objects.create(
            name="parse_statistic",
            related=self.allowed_resource,
            status=EventStatus.IN_PROGRESS,
            is_live_stream=True,
        )
        self.private_event_log = EventLog.objects.create(
            name="parse_statistic",
            related=self.private_resource,
            status=EventStatus.IN_PROGRESS,
            is_live_stream=True,
        )
        clear_live_log_history(self.allowed_event_log.pk)

    def test_allowed_event_log_connects(self):
        async def connect():
            communicator = WebsocketCommunicator(
                LiveLogConsumer.as_asgi(),
                f"/ws/live-log/?event_log_id={self.allowed_event_log.pk}",
            )
            communicator.scope["user"] = self.user
            connected, _ = await communicator.connect()
            snapshot = await communicator.receive_json_from() if connected else None
            if connected:
                await communicator.disconnect()
            return connected, snapshot

        connected, snapshot = async_to_sync(connect)()

        assert connected
        assert snapshot["event_log"]["id"] == self.allowed_event_log.pk

    def test_late_connection_replays_events_after_requested_sequence(self):
        append_live_log_history(
            self.allowed_event_log.pk,
            [
                {"seq": 1, "kind": "log", "level": "INFO", "message": "already received"},
                {"seq": 2, "kind": "log", "level": "INFO", "message": "missed while disconnected"},
            ],
        )

        async def connect():
            communicator = WebsocketCommunicator(
                LiveLogConsumer.as_asgi(),
                f"/ws/live-log/?event_log_id={self.allowed_event_log.pk}&after_seq=1",
            )
            communicator.scope["user"] = self.user
            connected, _ = await communicator.connect()
            snapshot = await communicator.receive_json_from()
            replay = await communicator.receive_json_from()
            await communicator.disconnect()
            return connected, snapshot, replay

        connected, snapshot, replay = async_to_sync(connect)()

        assert connected
        assert snapshot["type"] == "live_log_snapshot"
        assert [event["seq"] for event in replay["events"]] == [2]

    @override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
    def test_log_and_progress_events_are_delivered(self):
        events = [
            {"seq": 1, "kind": "log", "level": "INFO", "message": "working"},
            {
                "seq": 2,
                "kind": "progress",
                "bar_id": "bar-1",
                "description": "rows",
                "current": 1,
                "total": 2,
                "progress": 0.5,
                "completed": False,
            },
        ]

        async def receive_events():
            communicator = WebsocketCommunicator(
                LiveLogConsumer.as_asgi(),
                f"/ws/live-log/?event_log_id={self.allowed_event_log.pk}",
            )
            communicator.scope["user"] = self.user
            connected, _ = await communicator.connect()
            assert connected
            await communicator.receive_json_from()
            await get_channel_layer().group_send(
                get_live_log_group_name(self.allowed_event_log.pk),
                {
                    "type": "live_log",
                    "event_log_id": self.allowed_event_log.pk,
                    "events": events,
                },
            )
            message = await communicator.receive_json_from()
            await communicator.disconnect()
            return message

        message = async_to_sync(receive_events)()

        assert message["event_log_id"] == self.allowed_event_log.pk
        assert message["events"] == events

    def test_other_resource_event_log_is_rejected(self):
        async def connect():
            communicator = WebsocketCommunicator(
                LiveLogConsumer.as_asgi(),
                f"/ws/live-log/?event_log_id={self.private_event_log.pk}",
            )
            communicator.scope["user"] = self.user
            return await communicator.connect()

        connected, close_code = async_to_sync(connect)()

        assert not connected
        assert close_code == 4403
