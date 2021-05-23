from django.db import models

from clist.templatetags.extras import slug
from pyclist.models import BaseModel
from true_coders.models import Coder


class Chat(BaseModel):

    class ChatType(models.TextChoices):
        ROOM = 'ROOM', 'Room'
        PRIVATE = 'PRIV', 'Private'

    chat_type = models.CharField(
        max_length=4,
        choices=ChatType.choices,
        default=ChatType.ROOM,
        db_index=True,
    )
    name = models.TextField(null=False)
    slug = models.TextField(null=True, blank=True, db_index=True)

    def save(self, *args, **kwargs):
        self.slug = slug(self.name)
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.chat_type}__{self.name}'

    class Meta:
        indexes = [
            models.Index(fields=['chat_type']),
            models.Index(fields=['slug']),
            models.Index(fields=['chat_type', 'slug']),
        ]


class ChatLog(BaseModel):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE)
    coder = models.ForeignKey(Coder, on_delete=models.CASCADE, null=True, blank=True, default=None)
    action = models.CharField(max_length=20, null=False)
    context = models.JSONField(null=True, blank=True, default=dict)
