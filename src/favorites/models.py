from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from pyclist.models import BaseModel
from true_coders.models import Coder


class Activity(BaseModel):

    class Type(models.TextChoices):
        FAVORITE = 'fav', 'Favorite'
        LIKE = 'lik', 'Like'
        SOLVED = 'sol', 'Solved'
        REJECT = 'rej', 'Reject'
        TODO = 'tdo', 'Todo'

    coder = models.ForeignKey(Coder, on_delete=models.CASCADE)
    activity_type = models.CharField(max_length=3, choices=Type.choices)

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        verbose_name_plural = 'Activities'
        indexes = [
            models.Index(fields=['coder', 'activity_type', 'content_type', 'object_id']),
            models.Index(fields=['content_type', 'object_id', 'activity_type']),
        ]
        unique_together = ('coder', 'activity_type', 'content_type', 'object_id')
