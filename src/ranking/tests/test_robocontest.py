from types import SimpleNamespace
from unittest import mock

import pytest
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
            repeated_submissions = list(robocontest.process_submissions_url(ATTEMPTS_URL, submissions_info))
            pages[ATTEMPTS_URL]["props"]["pagination"]["items"][1]["status"] = 9
            judged_submissions = list(robocontest.process_submissions_url(ATTEMPTS_URL, submissions_info))

        assert [submission["id"] for submission in submissions] == [104, 102, 101]
        assert repeated_submissions == []
        assert [submission["id"] for submission in judged_submissions] == [103]
        assert submissions_info["last_submission_id"] == 104
        assert submissions_info["count"] == 4
        assert "pending_submission_ids" not in submissions_info

    def test_only_pending_submission_is_processed_after_judging(self):
        pages = {ATTEMPTS_URL: profile_page([make_item(101, status=0), make_item(100, status=9)])}
        submissions_info = {"last_submission_id": 100}

        with mock.patch.object(robocontest, "get_page_data", side_effect=pages.__getitem__):
            submissions = list(robocontest.process_submissions_url(ATTEMPTS_URL, submissions_info))
            assert submissions_info["pending_submission_ids"] == [101]
            pages[ATTEMPTS_URL]["props"]["pagination"]["items"][0]["status"] = 9
            judged_submissions = list(robocontest.process_submissions_url(ATTEMPTS_URL, submissions_info))

        assert submissions == []
        assert [submission["id"] for submission in judged_submissions] == [101]
        assert submissions_info["last_submission_id"] == 101
        assert submissions_info["count"] == 1
        assert "pending_submission_ids" not in submissions_info

    def test_multiple_pending_submissions_are_each_revisited(self):
        pages = {
            ATTEMPTS_URL: profile_page([
                make_item(105, status=0),
                make_item(104, status=9),
                make_item(103, status=1),
                make_item(102, status=8),
                make_item(100, status=9),
            ])
        }
        submissions_info = {"last_submission_id": 100}

        with mock.patch.object(robocontest, "get_page_data", side_effect=pages.__getitem__):
            first = list(robocontest.process_submissions_url(ATTEMPTS_URL, submissions_info))
            items = pages[ATTEMPTS_URL]["props"]["pagination"]["items"]
            items[0]["status"] = 9
            second = list(robocontest.process_submissions_url(ATTEMPTS_URL, submissions_info))
            items[2]["status"] = 10
            third = list(robocontest.process_submissions_url(ATTEMPTS_URL, submissions_info))

        assert [submission["id"] for submission in first] == [104, 102]
        assert [submission["id"] for submission in second] == [105]
        assert [submission["id"] for submission in third] == [103]
        assert submissions_info["count"] == 4
        assert submissions_info["last_submission_id"] == 105
        assert "pending_submission_ids" not in submissions_info


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

    def test_locale_headers_are_not_shared_with_requester(self):
        def get_page(url, **kwargs):
            kwargs["headers"]["Referer"] = url
            return "", 200

        with mock.patch.object(robocontest.REQ, "get", side_effect=get_page):
            assert robocontest.get_page_data(ATTEMPTS_URL) is None

        assert robocontest.LOCALE_HEADERS == {"X-LANG": "en"}


class RoboContestProfileTest(SimpleTestCase):
    resource = SimpleNamespace(profile_url="https://robocontest.uz/profile/{account}")

    def test_empty_successful_response_does_not_delete_account(self):
        with (
            mock.patch.object(robocontest.REQ, "get", return_value=("", 200)),
            pytest.raises(robocontest.ExceptionParseAccounts),
        ):
            list(robocontest.Statistic.get_users_infos(["user"], self.resource, []))

    def test_malformed_profile_raises_account_parse_error(self):
        with (
            mock.patch.object(robocontest, "get_page_data", return_value={"props": []}),
            pytest.raises(robocontest.ExceptionParseAccounts),
        ):
            list(robocontest.Statistic.get_users_infos(["user"], self.resource, []))

    def test_explicit_404_deletes_account(self):
        error = robocontest.FailOnGetResponse(SimpleNamespace(code=404))
        with mock.patch.object(robocontest, "get_page_data", side_effect=error):
            infos = list(robocontest.Statistic.get_users_infos(["user"], self.resource, []))

        assert infos == [{"delete": True}]


class RoboContestStandingsTest(SimpleTestCase):
    def parse_row(self, mode, row):
        page = {
            "props": {
                "tab": "standings",
                "tabData": {
                    "lastPage": 1,
                    "contestMode": mode,
                    "tasks": [{"letter": "A", "title": "Task", "maxScore": 100}],
                    "standings": [row],
                },
            }
        }
        contest = SimpleNamespace(submissions_info={})
        module = SimpleNamespace(url="https://robocontest.uz/olympiads/3951", contest=contest)

        with (
            mock.patch.object(
                robocontest,
                "get_page_data",
                side_effect=lambda url, **kwargs: page if url.endswith("/results?page=1") else None,
            ),
            mock.patch.object(robocontest, "process_submissions_url", return_value=[]),
        ):
            standings = robocontest.Statistic.get_standings(module)

        return standings["result"]["user"]

    def test_icpc_row_keeps_solved_tasks_and_penalty(self):
        row = {
            "participantUsername": "user",
            "rank": 1,
            "score": 4,
            "penalty": 120,
            "solvedCount": 4,
            "tasks": [{"solved": True, "attempts": 0, "time": "00:05"}],
        }

        result = self.parse_row("icpc", row)

        assert result["tasks"] == "4"
        assert result["penalty"] == 120
        assert result["problems"]["A"]["result"] == "+"

    def test_ioi_row_does_not_gain_penalty(self):
        row = {
            "participantUsername": "user",
            "rank": 1,
            "score": 60,
            "penalty": 0,
            "solvedCount": 0,
            "tasks": [{"score": 60, "maxScore": 100}],
        }

        result = self.parse_row("ioi", row)

        assert "penalty" not in result
        assert "tasks" not in result
        assert result["problems"]["A"] == {"result": 60, "partial": True}
