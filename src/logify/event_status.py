#!/usr/bin/env python3

from django.db import models


class EventStatus(models.TextChoices):
    NONE = 'none', 'None'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    IN_PROGRESS = 'in_progress', 'In Progress'
    CANCELLED = 'cancelled', 'Cancelled'
    SKIPPED = 'skipped', 'Skipped'
    INTERRUPTED = 'interrupted', 'Interrupted'
    WARNING = 'warning', 'Warning'
