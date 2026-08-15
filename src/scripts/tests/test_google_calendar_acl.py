import importlib.util
from pathlib import Path
from unittest.mock import Mock, call

ACL_PATH = next(
    parent / "legacy" / "api" / "google_calendar" / "acl.py"
    for parent in Path(__file__).parents
    if (parent / "legacy" / "api" / "google_calendar" / "acl.py").is_file()
)
SPEC = importlib.util.spec_from_file_location("google_calendar_acl", ACL_PATH)
assert SPEC
assert SPEC.loader
acl_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acl_module)


def request(response=None):
    value = Mock()
    value.execute.return_value = response or {}
    return value


def test_public_reader_acl_is_unchanged():
    service = Mock()
    acl = service.acl.return_value
    acl.list.return_value = request({
        "items": [{"id": "default", "role": "reader", "scope": {"type": "default"}}],
    })

    previous_role = acl_module.ensure_calendar_public(service, "calendar-id")

    assert previous_role == "reader"
    acl.insert.assert_not_called()
    acl.update.assert_not_called()


def test_missing_public_acl_is_inserted_as_reader():
    service = Mock()
    acl = service.acl.return_value
    acl.list.return_value = request({"items": []})
    acl.insert.return_value = request()

    previous_role = acl_module.ensure_calendar_public(service, "calendar-id")

    assert previous_role is None
    acl.insert.assert_called_once_with(
        calendarId="calendar-id",
        body={"role": "reader", "scope": {"type": "default"}},
        sendNotifications=False,
    )
    acl.insert.return_value.execute.assert_called_once_with()


def test_limited_public_acl_is_updated_to_reader():
    service = Mock()
    acl = service.acl.return_value
    acl.list.return_value = request({
        "items": [{"id": "default", "role": "freeBusyReader", "scope": {"type": "default"}}],
    })
    acl.update.return_value = request()

    previous_role = acl_module.ensure_calendar_public(service, "calendar-id")

    assert previous_role == "freeBusyReader"
    acl.update.assert_called_once_with(
        calendarId="calendar-id",
        ruleId="default",
        body={"role": "reader", "scope": {"type": "default"}},
        sendNotifications=False,
    )
    acl.update.return_value.execute.assert_called_once_with()


def test_dryrun_does_not_insert_missing_public_acl():
    service = Mock()
    acl = service.acl.return_value
    acl.list.return_value = request({"items": []})

    previous_role = acl_module.ensure_calendar_public(service, "calendar-id", dryrun=True)

    assert previous_role is None
    acl.insert.assert_not_called()
    acl.update.assert_not_called()


def test_public_acl_is_found_on_next_page():
    service = Mock()
    acl = service.acl.return_value
    acl.list.side_effect = [
        request({"items": [{"id": "user:test", "role": "reader", "scope": {"type": "user"}}], "nextPageToken": "next"}),
        request({"items": [{"id": "default", "role": "reader", "scope": {"type": "default"}}]}),
    ]

    previous_role = acl_module.ensure_calendar_public(service, "calendar-id")

    assert previous_role == "reader"
    assert acl.list.call_args_list == [
        call(calendarId="calendar-id", maxResults=250, pageToken=None),
        call(calendarId="calendar-id", maxResults=250, pageToken="next"),
    ]
