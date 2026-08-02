from logify.event_status import EventStatus
from logify.live import publish_live_log_status
from logify.models import EventLog


def _finish_live_event_logs(job, status, error):
    event_logs = EventLog.env_objects.finish_active(job.id, status=status, error=error)
    for event_log in event_logs:
        publish_live_log_status(event_log.pk, status, error)
    return event_logs


def interrupt_stale_event_logs(job_id, error):
    event_logs = EventLog.env_objects.finish_active(job_id, status=EventStatus.INTERRUPTED, error=error)
    for event_log in event_logs:
        publish_live_log_status(event_log.pk, EventStatus.INTERRUPTED, error)
    return len(event_logs) + EventLog.env_objects.interrupt_in_progress(job_id, error=error)


def fail_live_event_logs(job, connection, exception_type, exception_value, traceback):
    error = str(exception_value or exception_type or "RQ job failed")
    _finish_live_event_logs(job, EventStatus.FAILED, error)


def interrupt_live_event_logs(job, connection):
    error = "RQ job stopped"
    _finish_live_event_logs(job, EventStatus.INTERRUPTED, error)
