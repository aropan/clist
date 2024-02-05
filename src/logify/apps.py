from django.apps import AppConfig

from pyclist.decorators import run_once, run_only_in_production


class LogifyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'logify'

    @run_only_in_production
    @run_once('logify_ready')
    def ready(self):
        from logify.models import EventLog, EventStatus
        EventLog.objects.filter(status=EventStatus.IN_PROGRESS).update(status=EventStatus.INTERRUPTED)
