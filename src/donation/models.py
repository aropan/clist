from django.db import models

from pyclist.models import BaseManager, BaseModel


class EnabledDonationSource(BaseManager):
    def get_queryset(self):
        return super().get_queryset().filter(enable=True)


class DonationSource(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    url = models.URLField()
    icon = models.ImageField(upload_to='donation_sources', null=True, blank=True)
    enable = models.BooleanField(default=True)

    objects = BaseManager()
    enabled = EnabledDonationSource()

    def __str__(self):
        return f'{self.name} DonationSource#{self.id}'
