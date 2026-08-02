import re

from rq import Worker
from rq.job import JobStatus

# rq validate_job_id allows only letters, numbers, underscores and dashes
JOB_ID_DISALLOWED_RE = re.compile(r"[^A-Za-z0-9_-]")
ACTIVE_JOB_STATUSES = {
    JobStatus.CREATED,
    JobStatus.QUEUED,
    JobStatus.STARTED,
    JobStatus.DEFERRED,
    JobStatus.SCHEDULED,
}


def get_resource_job_id(prefix, host):
    return f"{prefix}_{JOB_ID_DISALLOWED_RE.sub('-', host)}"


def is_job_active(queue, job_id, job):
    if job and job.get_status(refresh=False) in ACTIVE_JOB_STATUSES:
        return True

    # The job hash can expire while an execution is still alive. RQ keeps the
    # execution and worker state separately, so consult both before enqueueing
    # another job with the same deterministic ID.
    if job_id in queue.started_job_registry.get_job_ids(cleanup=False):
        return True

    return any(worker.get_current_job_id() == job_id for worker in Worker.all(queue=queue))
