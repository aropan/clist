PUBLIC_SCOPE_TYPE = "default"
PUBLIC_ROLE = "reader"


def get_public_acl_rule(service, calendar_id):
    page_token = None
    while True:
        response = service.acl().list(calendarId=calendar_id, maxResults=250, pageToken=page_token).execute()
        for rule in response.get("items", []):
            if rule.get("scope", {}).get("type") == PUBLIC_SCOPE_TYPE:
                return rule

        page_token = response.get("nextPageToken")
        if not page_token:
            return None


def ensure_calendar_public(service, calendar_id, dryrun=False):
    """Ensure anonymous users can read a calendar and return its previous public role."""
    rule = get_public_acl_rule(service, calendar_id)
    previous_role = rule.get("role") if rule else None
    if previous_role == PUBLIC_ROLE or dryrun:
        return previous_role

    body = {
        "role": PUBLIC_ROLE,
        "scope": {"type": PUBLIC_SCOPE_TYPE},
    }
    acl = service.acl()
    if rule:
        acl.update(
            calendarId=calendar_id,
            ruleId=rule["id"],
            body=body,
            sendNotifications=False,
        ).execute()
    else:
        acl.insert(
            calendarId=calendar_id,
            body=body,
            sendNotifications=False,
        ).execute()
    return previous_role
