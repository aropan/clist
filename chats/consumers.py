import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer


@database_sync_to_async
def get_coder(user):
    return user.coder


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_group_name = 'room__general'
        self.user = self.scope['user']
        if self.user.is_authenticated:
            self.coder = await get_coder(self.user)

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    # Receive message from WebSocket
    async def receive(self, text_data):
        if not self.user.is_authenticated:
            return
        data = json.loads(text_data)
        data['from'] = {'coder': self.coder.username}
        action = data.pop('action')
        if action == 'new_message':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'new_message',
                    'message': data['message'],
                    'from': data['from'],
                }
            )

    # Receive message from room group
    async def new_message(self, event):
        # Send message to WebSocket
        await self.send(text_data=json.dumps(event))
