from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from pyclist.models import BaseModel
from true_coders.models import Coder


class Note(BaseModel):
    coder = models.ForeignKey(Coder, on_delete=models.CASCADE)
    text = models.TextField()

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        indexes = [
            models.Index(fields=['coder', 'content_type', 'object_id']),
            models.Index(fields=['content_type', 'object_id']),
        ]
        unique_together = ('coder', 'content_type', 'object_id')
