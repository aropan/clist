import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.shortcuts import get_object_or_404
from django.utils.timezone import now

from chats.models import Chat, ChatLog


@database_sync_to_async
def get_coder(user):
    return user.coder


def get_chat(name):
    chat_type, chat_slug = name.split('__')
    ret = get_object_or_404(Chat, chat_type=chat_type.upper(), slug=chat_slug)
    return ret


@database_sync_to_async
def add_chat_log(chat, coder, action, context):
    if not isinstance(chat, Chat):
        chat = get_chat(chat)
    ChatLog.objects.create(chat=chat, coder=coder, action=action, context=context)


@database_sync_to_async
def get_logs(chat, from_id):
    if not isinstance(chat, Chat):
        chat = get_chat(chat)
    ret = ChatLog.objects.filter(chat=chat)
    if from_id:
        ret = ret.filter(pk__lt=int(from_id))
    ret = ret.order_by('-created')[:20]
    return list(ret)


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
        data = json.loads(text_data)
        action = data.pop('action')
        context = {
            'type': action,
            'chat': data['chat'],
            'when': str(now()),
        }

        if self.user.is_authenticated:
            context['from'] = {'coder': self.coder.username}
        elif action not in ['get_logs']:
            return

        if action == 'new_message':
            context['message'] = data['message']
            await self.channel_layer.group_send(self.room_group_name, context)
        elif action == 'get_logs':
            logs = await get_logs(data['chat'], data['id'])
            context = [{'data': d.context, 'id': d.pk} for d in logs]
            await self.send(text_data=json.dumps({
                'type': 'history',
                'history': context,
            }))
            return
        else:
            return
        await add_chat_log(data['chat'], self.coder, action, context)

    # Receive message from room group
    async def new_message(self, event):
        # Send message to WebSocket
        await self.send(text_data=json.dumps(event))
