from unittest import mock

from django.test import SimpleTestCase

from ranking.management.modules import robocontest

ATTEMPTS_URL = "https://robocontest.uz/profile/user/attempts"


def make_item(submission_id, status, **overrides):
    item = {
        "id": submission_id,
        "status": status,
        "isAccepted": status in (9, 10),
        "isUpsolve": False,
        "activeTest": 3,
        "runTime": 15,
        "runMemory": 1024,
        "createdAt": "2026-09-13T10:00:00.000000Z",
        "task": {"title": "Task", "number": "R112A"},
        "user": {"username": "user"},
        "language": {"name": "cpp"},
    }
    item.update(overrides)
    return item


def profile_page(items, next_url=None):
    return {"component": "Attempts/Index", "props": {"pagination": {"items": items, "nextUrl": next_url}}}


class RoboContestSubmissionVerdictTest(SimpleTestCase):
    def test_partially_accepted_submission_is_not_a_full_accept(self):
        submission = robocontest.parse_submission(make_item(11200067, status=10))

        assert submission["binary"] is False
        assert submission["verdict"] == "PA"
        assert submission["verdict_full"] == "Partially accepted"

    def test_accepted_submission_is_a_full_accept(self):
        submission = robocontest.parse_submission(make_item(11200068, status=9))

        assert submission["binary"] is True
        assert submission["verdict"] == "AC"

    def test_failed_verdict_keeps_the_test_number(self):
        submission = robocontest.parse_submission(make_item(11200069, status=8, activeTest=4))

        assert submission["verdict"] == "WA"
        assert submission["test"] == 4

    def test_optional_nested_fields_may_be_missing(self):
        submission = robocontest.parse_submission(make_item(11200070, status=9, task=None, language=None))

        assert submission["task_name"] is None
        assert submission["language"] is None
        assert "task_id" not in submission

    def test_submission_without_a_user_is_skipped(self):
        assert robocontest.parse_submission(make_item(11200071, status=9, user=None)) is None


class RoboContestSubmissionsCheckpointTest(SimpleTestCase):
    def test_pending_submission_is_revisited_on_the_next_run(self):
        second_page_url = f"{ATTEMPTS_URL}?page=cursor"
        pages = {
            ATTEMPTS_URL: profile_page(
                [make_item(104, status=9), make_item(103, status=1), make_item(102, status=8)],
                next_url="http://robocontest.uz/profile/user/attempts?page=cursor",
            ),
            second_page_url: profile_page([make_item(101, status=9), make_item(100, status=9)]),
        }
        submissions_info = {"last_submission_id": 100}

        with mock.patch.object(robocontest, "get_page_data", side_effect=pages.__getitem__):
            submissions = list(robocontest.process_submissions_url(ATTEMPTS_URL, submissions_info))

        assert [submission["id"] for submission in submissions] == [104, 102, 101]
        assert submissions_info["last_submission_id"] == 102
        assert submissions_info["count"] == 3

    def test_checkpoint_does_not_move_back_when_only_pending_submissions_are_new(self):
        pages = {ATTEMPTS_URL: profile_page([make_item(101, status=0), make_item(100, status=9)])}
        submissions_info = {"last_submission_id": 100}

        with mock.patch.object(robocontest, "get_page_data", side_effect=pages.__getitem__):
            submissions = list(robocontest.process_submissions_url(ATTEMPTS_URL, submissions_info))

        assert submissions == []
        assert submissions_info["last_submission_id"] == 100


class RoboContestInertiaPageTest(SimpleTestCase):
    def test_reads_the_script_tag_envelope_and_skips_other_json_scripts(self):
        page = (
            '<div id="robo-app"></div>'
            '<script data-inertia-devtools-id type="application/json">"01M1WW0BJP"</script>'
            '<script type="application/json">{"component": "Contest/Show", "props": {"tab": "standings"}}</script>'
        )

        data = robocontest.parse_inertia_page(page, "url")

        assert data == {"component": "Contest/Show", "props": {"tab": "standings"}}

    def test_reads_the_data_page_attribute_envelope(self):
        page = (
            '<div id="robo-app" data-page="{&quot;component&quot;:&quot;Contest/Show&quot;,'
            '&quot;props&quot;:{&quot;tab&quot;:&quot;standings&quot;}}"></div>'
        )

        data = robocontest.parse_inertia_page(page, "url")

        assert data == {"component": "Contest/Show", "props": {"tab": "standings"}}

    def test_next_submissions_url_restores_the_tab_and_scheme(self):
        pagination = {"nextUrl": "http://robocontest.uz/contests/3941?page=cursor"}

        next_url = robocontest.next_submissions_url(
            pagination, "https://robocontest.uz/contests/3941/attempts", "submissions"
        )

        assert next_url == "https://robocontest.uz/contests/3941?page=cursor&tab=submissions"

    def test_next_submissions_url_is_none_on_the_last_page(self):
        assert robocontest.next_submissions_url({"nextUrl": None}, ATTEMPTS_URL, None) is None
