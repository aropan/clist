from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.shortcuts import get_object_or_404

from clist.models import Contest
from clist.templatetags.extras import has_update_statistics_permission, is_anonymous_user


@database_sync_to_async
def get_contest(pk):
    return get_object_or_404(Contest, pk=pk)


@database_sync_to_async
def get_coder(user):
    return user.coder if not is_anonymous_user(user) else None


@database_sync_to_async
def get_update_statistics_permission(user, contest):
    return has_update_statistics_permission(user, contest)


class ContestConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        params = parse_qs(self.scope['query_string'].decode())
        self.contest = await get_contest(pk=params['pk'][0])
        self.user = self.scope['user']

        await self.channel_layer.group_add(self.group_name, self.channel_name)

        self.has_update_statistics = await get_update_statistics_permission(self.user, self.contest)
        if self.has_update_statistics:
            await self.channel_layer.group_add(self.update_statistics_group_name, self.channel_name)

        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

        if self.has_update_statistics:
            await self.channel_layer.group_discard(self.update_statistics_group_name, self.channel_name)

    @property
    def group_name(self):
        return self.contest.channel_group_name

    @property
    def update_statistics_group_name(self):
        return self.contest.channel_update_statistics_group_name

    async def standings(self, data):
        await self.send_json(data)

    async def update_statistics(self, data):
        await self.send_json(data)
