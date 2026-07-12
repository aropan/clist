import re

# rq validate_job_id allows only letters, numbers, underscores and dashes
JOB_ID_DISALLOWED_RE = re.compile(r'[^A-Za-z0-9_-]')


def get_resource_job_id(prefix, host):
    return f'{prefix}_{JOB_ID_DISALLOWED_RE.sub("-", host)}'
