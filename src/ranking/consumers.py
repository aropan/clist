from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.shortcuts import get_object_or_404

from clist.models import Contest


@database_sync_to_async
def get_contest(pk):
    return get_object_or_404(Contest, pk=pk)


class ContestConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        params = parse_qs(self.scope['query_string'].decode())
        self.contest = await get_contest(pk=params['pk'][0])
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    @property
    def group_name(self):
        return self.contest.channel_group_name
