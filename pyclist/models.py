from django.db import models


class BaseModel(models.Model):
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    modified = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True


class BaseManager(models.Manager):

    class Meta:
        abstract = True
