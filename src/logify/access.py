from django.contrib.contenttypes.models import ContentType
from django.db.models import Q, Subquery
from guardian.models import GroupObjectPermission, UserObjectPermission

from clist.models import Contest, Resource
from logify.event_status import EventStatus
from logify.models import EventLog
from ranking.models import Stage

ACTIVE_LIVE_STATUSES = (EventStatus.NONE, EventStatus.IN_PROGRESS)
LIVE_RELATED_MODELS = ("contest", "resource")


def can_view_any_live_updates(user):
    if not user or not user.is_authenticated:
        return False
    if user.has_perm("logify.view_all_live_updates"):
        return True

    permission_filter = {
        "permission__codename": "view_live_updates",
        "permission__content_type__app_label": "clist",
        "permission__content_type__model__in": LIVE_RELATED_MODELS,
    }
    return (
        UserObjectPermission.objects.filter(user=user, **permission_filter).exists()
        or GroupObjectPermission.objects.filter(group__user=user, **permission_filter).exists()
    )


def can_view_live_related(user, related):
    if not user or not user.is_authenticated:
        return False
    if user.has_perm("logify.view_all_live_updates"):
        return True

    if isinstance(related, Resource):
        return user.has_perm("view_live_updates", related)
    if isinstance(related, Contest):
        return user.has_perm("view_live_updates", related) or user.has_perm("view_live_updates", related.resource)
    if isinstance(related, Stage):
        contest = related.contest
        return user.has_perm("view_live_updates", contest) or user.has_perm("view_live_updates", contest.resource)
    return False


def can_view_live_event_log(user, event_log):
    return can_view_live_related(user, event_log.related)


def get_active_live_event_logs(user, *, limit=100):
    if limit <= 0:
        return []
    event_logs = (
        EventLog.env_objects.filter(is_live_stream=True, status__in=ACTIVE_LIVE_STATUSES)
        .select_related("content_type")
        .order_by("-created")
    )
    visible_event_logs = []
    for event_log in event_logs.iterator(chunk_size=max(limit, 1)):
        if can_view_live_event_log(user, event_log):
            visible_event_logs.append(event_log)
            if len(visible_event_logs) >= limit:
                break
    return visible_event_logs


def get_live_event_log_for_job(user, job_id):
    event_logs = EventLog.env_objects.filter(is_live_stream=True, job_id=job_id).order_by("-created")
    return next(
        (event_log for event_log in event_logs if can_view_live_event_log(user, event_log)),
        None,
    )


def get_live_event_log_for_contest(user, contest):
    if not can_view_live_related(user, contest):
        return None

    contest_content_type = ContentType.objects.get_for_model(Contest)
    contest_job_ids = EventLog.env_objects.filter(
        content_type=contest_content_type,
        object_id=contest.pk,
        name="parse_statistic",
        status__in=ACTIVE_LIVE_STATUSES,
        job_id__isnull=False,
    ).values("job_id")
    event_logs = (
        EventLog.env_objects.filter(
            is_live_stream=True,
            name="parse_statistic",
            status__in=ACTIVE_LIVE_STATUSES,
        )
        .filter(Q(content_type=contest_content_type, object_id=contest.pk) | Q(job_id__in=Subquery(contest_job_ids)))
        .order_by("-created")
    )
    return next(
        (event_log for event_log in event_logs if can_view_live_event_log(user, event_log)),
        None,
    )


def serialize_live_event_log(event_log):
    related = event_log.related
    related_type = related._meta.model_name if related is not None else None
    related_name = str(related) if related is not None else "Deleted object"
    url = None
    if isinstance(related, Contest):
        related_name = related.title
        url = related.actual_url
    elif isinstance(related, Resource):
        related_name = related.host
        url = related.href()
    elif isinstance(related, Stage):
        related_name = str(related)
        url = related.contest.actual_url

    status = "queued" if event_log.status == EventStatus.NONE and event_log.job_id else event_log.status
    return {
        "id": event_log.pk,
        "name": event_log.name,
        "status": status,
        "message": event_log.message,
        "job_id": event_log.job_id,
        "created": event_log.created.isoformat(),
        "modified": event_log.modified.isoformat(),
        "related_type": related_type,
        "related_name": related_name,
        "url": url,
    }
