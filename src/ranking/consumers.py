from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.shortcuts import get_object_or_404

from clist.models import Contest
from logify.access import can_view_live_event_log, serialize_live_event_log
from logify.live import get_live_log_group_name, get_live_log_history
from logify.models import EventLog


@database_sync_to_async
def get_contest(pk):
    return get_object_or_404(Contest, pk=pk)


@database_sync_to_async
def get_live_event_log(user, pk):
    try:
        event_log = EventLog.env_objects.select_related("content_type").get(pk=pk, is_live_stream=True)
    except EventLog.DoesNotExist:
        return None
    if not can_view_live_event_log(user, event_log):
        return None
    return serialize_live_event_log(event_log)


class ContestConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        params = parse_qs(self.scope["query_string"].decode())
        self.contest = await get_contest(pk=params["pk"][0])
        self.user = self.scope["user"]

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    @property
    def group_name(self):
        return self.contest.channel_group_name

    async def standings(self, data):
        await self.send_json(data)


class LiveLogConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        try:
            params = parse_qs(self.scope["query_string"].decode())
            event_log_id = int(params["event_log_id"][0])
            after_seq = max(int(params.get("after_seq", [0])[0]), 0)
        except KeyError, TypeError, ValueError:
            await self.close(code=4400)
            return

        event_log = await get_live_event_log(self.scope["user"], event_log_id)
        if event_log is None:
            await self.close(code=4403)
            return

        self.event_log_id = event_log_id
        self.group_name = get_live_log_group_name(event_log_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        event_log = await get_live_event_log(self.scope["user"], event_log_id)
        if event_log is None:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            await self.close(code=4403)
            return
        await self.accept()
        await self.send_json({
            "type": "live_log_snapshot",
            "event_log": event_log,
        })
        history = await sync_to_async(get_live_log_history, thread_sensitive=False)(event_log_id, after_seq)
        if history:
            await self.send_json({
                "type": "live_log",
                "event_log_id": event_log_id,
                "events": history,
            })

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def live_log(self, data):
        await self.send_json(data)
