from logging import getLogger
from time import monotonic

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from clist.models import Resource
from clist.resource_activity import get_resource_activity_scores


class Command(BaseCommand):
    help = "Update daily Activity scores for all resources"

    def handle(self, *args, **options):
        started = monotonic()
        now = timezone.now()
        scores = get_resource_activity_scores(now)
        resource_ids = list(Resource.objects.values_list("pk", flat=True))
        updates = [
            Resource(pk=resource_id, activity_score=scores.get(resource_id, 0), activity_updated_at=now)
            for resource_id in resource_ids
        ]

        with transaction.atomic():
            updated = Resource.objects.bulk_update(updates, ["activity_score", "activity_updated_at"], batch_size=100)

        message = f"Updated Activity for {updated} resources in {monotonic() - started:.2f}s"
        getLogger("clist.update_resource_activity").info(message)
        self.stdout.write(message)
