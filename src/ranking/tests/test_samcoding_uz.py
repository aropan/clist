from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import pytest
from django.test import SimpleTestCase, TestCase

from clist.models import Contest, Resource
from notification.utils import compose_message_by_submissions
from ranking.management.modules import samcoding_uz
from ranking.management.modules.excepts import ExceptionParseAccounts, ExceptionParseStandings, FailOnGetResponse
from ranking.models import Account, Statistics

CONTEST_URL = "https://samcoding.uz/api/contests/16/"


def page(number, pages, rows, total=None):
    return {"page": number, "pagesCount": pages, "data": rows, "total": total}


def submission(submission_id, score=500, relative_time_seconds=60):
    return {
        "id": submission_id,
        "username": "coder",
        "problem": "A",
        "score": score,
        "relative_time_seconds": relative_time_seconds,
        "language": "Python 3.12",
        "verdict": "Accepted",
        "time_used": 25,
        "memory_used": 1024,
    }


class SamcodingParserTest(SimpleTestCase):
    def setUp(self):
        self.contest = SimpleNamespace(
            pk=16,
            key="16",
            title="Round 6",
            url="https://samcoding.uz/contest/16",
            standings_url=None,
            start_time=None,
            end_time=None,
            info={},
            resource=None,
            invisible=False,
            duration=timedelta(minutes=150),
            submissions_info={"last_submission_id": 150, "count": 10, "upsolving_version": 1},
        )
        self.contest_data = {
            "format_type": "ioi",
            "problems": [{"letter": "A", "problem_title": "Task A", "url": "https://samcoding.uz/A", "score": 500}],
        }
        self.clist_data = {
            "status": "ok",
            "url": "https://samcoding.uz/contests/16/standings",
            "problems": [{"short": "A", "archive_url": "https://samcoding.uz/problems/16/A", "tags": ["Math"]}],
            "standings": [{"member": "coder", "place": 1}],
        }
        self.row = {
            "username": "coder",
            "rank": 1,
            "total_score": 500,
            "solved_count": 1,
            "first_name": "Code",
            "last_name": "Writer",
            "country_code": "uz",
            "problems_data": {"A": {"score": 500, "attempts": 2, "solved": True, "time": 9}},
        }

    def parse_standings(self, submissions=(), statistics=None, rows=None):
        total = len(submissions)
        responses = {
            CONTEST_URL: self.contest_data,
            CONTEST_URL + "clist-standings/": self.clist_data,
            CONTEST_URL + "standings/?page=1": page(1, 1, [self.row] if rows is None else rows),
            CONTEST_URL + "submissions/?page=1&pageSize=1": page(1, total, list(submissions[:1]), total),
            CONTEST_URL + f"submissions/?page={total}&pageSize=1": page(total, total, list(submissions[-1:]), total),
            CONTEST_URL + "submissions/?page=1&pageSize=100": page(1, 1, list(submissions), total),
        }
        with mock.patch.object(samcoding_uz.REQ, "get", side_effect=lambda url, **kwargs: responses[url]):
            return samcoding_uz.Statistic(contest=self.contest).get_standings(statistics=statistics)

    def test_clist_places_and_archive_metadata_with_partial_scores(self):
        self.clist_data["standings"][0]["place"] = None
        self.clist_data["standings"][0]["problems"] = {"A": {"result": "-2"}}
        self.row["problems_data"]["A"].update(score=300, solved=False)
        self.row["total_score"] = 300
        self.row["rating"] = None

        standings = self.parse_standings()

        row = standings["result"]["coder"]
        assert row["place"] is None
        assert row["_no_update_n_contests"] is True
        assert row["solving"] == 300
        assert row["problems"]["A"] == {"result": 300, "attempts": 2, "partial": True, "time": "0:09"}
        assert "old_rating" not in row
        assert "new_rating" not in row
        assert standings["url"] == self.clist_data["url"]
        assert standings["standings_kind"] == "scoring"
        assert standings["problems"][0]["archive_url"] == "https://samcoding.uz/problems/16/A"
        assert standings["problems"][0]["tags"] == ["Math"]

    def test_clist_place_overrides_rank_without_excluding_ranked_users(self):
        self.clist_data["standings"][0]["place"] = 2

        row = self.parse_standings()["result"]["coder"]

        assert row["place"] == 2
        assert "_no_update_n_contests" not in row

    def test_missing_clist_member_fails_instead_of_using_rank(self):
        self.clist_data["standings"] = []
        with pytest.raises(ExceptionParseStandings, match="Missing member coder"):
            self.parse_standings()

    def test_invalid_clist_response_is_rejected(self):
        self.clist_data["status"] = "error"
        with pytest.raises(ExceptionParseStandings, match="Unexpected standings response"):
            self.parse_standings()

    def test_upsolve_flag_separates_submissions_and_keeps_best_score(self):
        self.row["problems_data"]["A"].update(score=200, solved=False)
        submissions = [
            submission(151, score=300) | {"is_upsolve": True, "verdict": "Wrong Answer #3"},
            submission(152, score=100) | {"is_upsolve": True, "verdict": "Wrong Answer #2"},
            submission(153, score=200, relative_time_seconds=9001) | {"is_upsolve": False},
        ]

        problem = self.parse_standings(submissions)["result"]["coder"]["problems"]["A"]

        assert problem["result"] == 200
        assert problem["submission_id"] == 153
        assert problem["upsolving"]["result"] == 300
        assert problem["upsolving"]["partial"] is True
        assert problem["upsolving"]["submission_id"] == 151
        assert problem["upsolving"]["verdict"] == "WA"
        assert problem["upsolving"]["test"] == 3

    def test_upsolving_without_contest_attempts_survives_next_parse(self):
        self.row["problems_data"] = {}
        first = self.parse_standings([submission(151) | {"is_upsolve": True}])
        self.contest.submissions_info = first["submissions_info"]

        second = self.parse_standings([submission(151) | {"is_upsolve": True}], statistics=first["result"])

        assert first["result"]["coder"]["problems"]["A"] == second["result"]["coder"]["problems"]["A"]
        assert second["result"]["coder"]["problems"]["A"]["upsolving"]["result"] == 500
        assert "partial" not in second["result"]["coder"]["problems"]["A"]["upsolving"]

    def test_upsolve_only_participant_survives_next_parse(self):
        submissions = [submission(151) | {"username": "upsolver", "is_upsolve": True}]
        first = self.parse_standings(submissions)
        self.contest.submissions_info = first["submissions_info"]

        second = self.parse_standings(submissions, statistics=first["result"])

        assert second["result"]["upsolver"] == first["result"]["upsolver"]
        assert second["result"]["upsolver"]["place"] is None
        assert second["result"]["upsolver"]["_no_update_n_contests"] is True

    def test_contest_submission_does_not_fill_an_upsolving_only_problem(self):
        self.row["problems_data"] = {}
        statistics = {"coder": {"problems": {"A": {"upsolving": {"result": 500, "submission_id": 149}}}}}

        standings = self.parse_standings([submission(151) | {"is_upsolve": False}], statistics=statistics)

        problem = standings["result"]["coder"]["problems"]["A"]
        assert problem == statistics["coder"]["problems"]["A"]
        assert problem is not statistics["coder"]["problems"]["A"]

    def test_old_cursor_replays_upsolving_once_without_doubling_count(self):
        self.contest.submissions_info = {"last_submission_id": 151, "count": 20}
        submissions = [submission(150), submission(151) | {"is_upsolve": True}]
        standings = self.parse_standings(submissions)

        assert standings["submissions_info"] == {"last_submission_id": 151, "count": 2, "upsolving_version": 1}
        assert standings["result"]["coder"]["problems"]["A"]["upsolving"]["submission_id"] == 151
        assert self.contest.submissions_info == {"last_submission_id": 151, "count": 20}

    def test_icpc_upsolving_does_not_replace_contest_results(self):
        self.contest_data["format_type"] = "icpc"
        self.row["penalty"] = 0
        self.row["problems_data"]["A"].update(solved=False, attempts=3)
        submissions = [
            submission(151, score=0) | {"is_upsolve": True, "verdict": "Wrong Answer #1"},
            submission(152, score=0) | {"is_upsolve": True},
            submission(153, score=0) | {"is_upsolve": True, "verdict": "Wrong Answer #2"},
        ]

        problem = self.parse_standings(submissions)["result"]["coder"]["problems"]["A"]

        assert problem["result"] == "-3"
        assert "submission_id" not in problem
        assert problem["upsolving"]["result"] == "+"
        assert problem["upsolving"]["submission_id"] == 152

    def test_failed_icpc_upsolve_is_recorded(self):
        self.contest_data["format_type"] = "icpc"
        self.row["penalty"] = 0
        submissions = [submission(151, score=0) | {"is_upsolve": True, "verdict": "Wrong Answer #1"}]

        problem = self.parse_standings(submissions)["result"]["coder"]["problems"]["A"]

        assert problem["upsolving"]["result"] == "-"
        assert problem["upsolving"]["verdict"] == "WA"

    def test_pending_upsolve_is_retried_without_new_submissions(self):
        submissions_info = self.contest.submissions_info
        for format_type in ("icpc", "ioi"):
            with self.subTest(format_type=format_type):
                self.contest.submissions_info = submissions_info
                self.contest_data["format_type"] = format_type
                self.row["penalty"] = 0
                pending = submission(151, score=None) | {"is_upsolve": True, "verdict": "Running"}

                first = self.parse_standings([pending])

                assert "upsolving" not in first["result"]["coder"]["problems"]["A"]
                assert first["submissions_info"]["pending_submission_ids"] == [151]
                self.contest.submissions_info = first["submissions_info"]
                accepted = submission(151) | {"is_upsolve": True}
                second = self.parse_standings([accepted], statistics=first["result"])

                upsolving = second["result"]["coder"]["problems"]["A"]["upsolving"]
                assert upsolving["verdict"] == "AC"
                assert upsolving["result"] == ("+" if format_type == "icpc" else 500)
                assert upsolving["submission_id"] == 151
                assert second["submissions_info"] == {"last_submission_id": 151, "count": 11, "upsolving_version": 1}

    def test_pending_upsolve_can_finish_with_wrong_answer(self):
        pending = submission(151, score=None) | {"is_upsolve": True, "verdict": "Compiling"}
        first = self.parse_standings([pending])
        self.contest.submissions_info = first["submissions_info"]
        rejected = submission(151, score=100) | {"is_upsolve": True, "verdict": "Wrong Answer #2"}

        second = self.parse_standings([rejected], statistics=first["result"])

        upsolving = second["result"]["coder"]["problems"]["A"]["upsolving"]
        assert upsolving["result"] == 100
        assert upsolving["partial"] is True
        assert upsolving["verdict"] == "WA"
        assert "pending_submission_ids" not in second["submissions_info"]
        assert second["submissions_info"]["count"] == first["submissions_info"]["count"]

    def test_pending_submission_keeps_its_id_until_judged(self):
        pending = submission(151, score=None) | {"is_upsolve": True, "verdict": "Pending"}
        first = self.parse_standings([pending])
        self.contest.submissions_info = first["submissions_info"]

        second = self.parse_standings([pending], statistics=first["result"])

        assert second["submissions_info"] == first["submissions_info"]
        assert "upsolving" not in second["result"]["coder"]["problems"]["A"]

    def test_pending_submission_on_older_page_is_retried(self):
        self.contest.submissions_info = {
            "last_submission_id": 202,
            "count": 13,
            "upsolving_version": 1,
            "pending_submission_ids": [101],
        }
        accepted = submission(101) | {"is_upsolve": True}
        responses = {
            CONTEST_URL: self.contest_data,
            CONTEST_URL + "clist-standings/": self.clist_data,
            CONTEST_URL + "standings/?page=1": page(1, 1, [self.row]),
            CONTEST_URL + "submissions/?page=1&pageSize=1": page(1, 202, [submission(1)], 202),
            CONTEST_URL + "submissions/?page=202&pageSize=1": page(202, 202, [submission(202)], 202),
            CONTEST_URL + "submissions/?page=3&pageSize=100": page(3, 3, [submission(201), submission(202)], 202),
            CONTEST_URL + "submissions/?page=2&pageSize=100": page(2, 3, [accepted, submission(151)], 202),
        }

        with mock.patch.object(samcoding_uz.REQ, "get", side_effect=lambda url, **kwargs: responses[url]):
            standings = samcoding_uz.Statistic(contest=self.contest).get_standings()

        upsolving = standings["result"]["coder"]["problems"]["A"]["upsolving"]
        assert upsolving["submission_id"] == 101
        assert upsolving["verdict"] == "AC"
        assert standings["submissions_info"] == {"last_submission_id": 202, "count": 13, "upsolving_version": 1}

    def test_standings_and_new_submissions_only(self):
        responses = {
            CONTEST_URL: self.contest_data,
            CONTEST_URL + "clist-standings/": self.clist_data,
            CONTEST_URL + "standings/?page=1": page(1, 2, [self.row]),
            CONTEST_URL + "standings/?page=2": page(2, 2, []),
            CONTEST_URL + "submissions/?page=1&pageSize=1": page(1, 202, [submission(1)], 202),
            CONTEST_URL + "submissions/?page=202&pageSize=1": page(202, 202, [submission(202, 0)], 202),
            CONTEST_URL + "submissions/?page=3&pageSize=100": page(3, 3, [submission(201), submission(202, 0)], 202),
            CONTEST_URL + "submissions/?page=2&pageSize=100": page(2, 3, [submission(101), submission(151)], 202),
        }
        statistics = {"coder": {"problems": {"A": {"result": 500, "submission_id": 149}}}}

        with mock.patch.object(
            samcoding_uz.REQ, "get", side_effect=lambda url, **kwargs: responses[url]
        ) as request_get:
            standings = samcoding_uz.Statistic(contest=self.contest).get_standings(statistics=statistics)

        assert request_get.call_count == 8
        assert all(call.kwargs["headers"]["Accept-Language"] == "en" for call in request_get.call_args_list)
        requested_urls = [call.args[0] for call in request_get.call_args_list]
        assert CONTEST_URL + "submissions/?page=1&pageSize=100" not in requested_urls
        assert standings["submissions_info"] == {"last_submission_id": 202, "count": 13, "upsolving_version": 1}
        assert self.contest.submissions_info == {"last_submission_id": 150, "count": 10, "upsolving_version": 1}
        assert standings["result"]["coder"]["name"] == "Code Writer"
        assert standings["result"]["coder"]["country"] == "UZ"
        assert standings["result"]["coder"]["problems"]["A"] == {
            "result": 500,
            "attempts": 2,
            "time": "0:09",
            "submission_id": 201,
            "language": "Python 3.12",
            "verdict": "AC",
            "verdict_full": "Accepted",
            "exec_time": "25 ms",
            "memory_usage": "1024 KB",
        }

    def test_old_verbose_verdict_is_shortened_without_new_submissions(self):
        responses = {
            CONTEST_URL: self.contest_data,
            CONTEST_URL + "clist-standings/": self.clist_data,
            CONTEST_URL + "standings/?page=1": page(1, 1, [self.row]),
            CONTEST_URL + "submissions/?page=1&pageSize=1": page(1, 150, [submission(1)], 150),
            CONTEST_URL + "submissions/?page=150&pageSize=1": page(150, 150, [submission(150)], 150),
        }
        statistics = {"coder": {"problems": {"A": {"result": 500, "submission_id": 149, "verdict": "Wrong Answer #1"}}}}

        with mock.patch.object(samcoding_uz.REQ, "get", side_effect=lambda url, **kwargs: responses[url]):
            standings = samcoding_uz.Statistic(contest=self.contest).get_standings(statistics=statistics)

        problem = standings["result"]["coder"]["problems"]["A"]
        assert problem["verdict"] == "WA"
        assert problem["verdict_full"] == "Wrong Answer #1"
        assert problem["test"] == 1
        assert problem["submission_id"] == 149

    def test_verdict_codes_and_failed_test_numbers(self):
        assert samcoding_uz.parse_verdict("Runtime Error #1") == {
            "verdict": "RE",
            "verdict_full": "Runtime Error #1",
            "test": 1,
        }
        assert samcoding_uz.parse_verdict("Time Limit #47") == {
            "verdict": "TL",
            "verdict_full": "Time Limit #47",
            "test": 47,
        }

    def test_legacy_submissions_outside_contest_are_upsolving(self):
        responses = {
            CONTEST_URL: self.contest_data,
            CONTEST_URL + "clist-standings/": self.clist_data,
            CONTEST_URL + "standings/?page=1": page(1, 1, [self.row]),
            CONTEST_URL + "submissions/?page=1&pageSize=1": page(1, 2, [submission(150)], 2),
            CONTEST_URL + "submissions/?page=2&pageSize=1": page(2, 2, [submission(151)], 2),
            CONTEST_URL + "submissions/?page=1&pageSize=100": page(
                1, 1, [submission(150), submission(151, relative_time_seconds=9001)], 2
            ),
        }

        with mock.patch.object(samcoding_uz.REQ, "get", side_effect=lambda url, **kwargs: responses[url]):
            standings = samcoding_uz.Statistic(contest=self.contest).get_standings()

        assert "submission_id" not in standings["result"]["coder"]["problems"]["A"]
        assert standings["submissions_info"]["last_submission_id"] == 151
        assert standings["result"]["coder"]["problems"]["A"]["upsolving"]["submission_id"] == 151

    def test_unchanged_submissions_fetch_only_latest_record(self):
        responses = {
            CONTEST_URL: self.contest_data,
            CONTEST_URL + "clist-standings/": self.clist_data,
            CONTEST_URL + "standings/?page=1": page(1, 1, [self.row]),
            CONTEST_URL + "submissions/?page=1&pageSize=1": page(1, 150, [submission(1)], 150),
            CONTEST_URL + "submissions/?page=150&pageSize=1": page(150, 150, [submission(150)], 150),
        }

        with mock.patch.object(
            samcoding_uz.REQ, "get", side_effect=lambda url, **kwargs: responses[url]
        ) as request_get:
            standings = samcoding_uz.Statistic(contest=self.contest).get_standings()

        assert request_get.call_count == 5
        assert standings["submissions_info"] == self.contest.submissions_info

    def test_icpc_uses_solved_count_penalty_and_attempts(self):
        contest_data = self.contest_data | {
            "format_type": "icpc",
            "problems": self.contest_data["problems"]
            + [{"letter": "B", "problem_title": "Task B", "url": "https://samcoding.uz/B", "score": 100}],
        }
        row = self.row | {
            "total_score": 100,
            "penalty": 29,
            "problems_data": {
                "A": {"solved": True, "attempts": 2, "time": 9},
                "B": {"solved": False, "attempts": 3, "time": 0},
            },
        }
        responses = {
            CONTEST_URL: contest_data,
            CONTEST_URL + "clist-standings/": self.clist_data,
            CONTEST_URL + "standings/?page=1": page(1, 1, [row]),
            CONTEST_URL + "submissions/?page=1&pageSize=1": page(1, 2, [submission(151, score=0)], 2),
            CONTEST_URL + "submissions/?page=2&pageSize=1": page(2, 2, [submission(152, score=0)], 2),
            CONTEST_URL + "submissions/?page=1&pageSize=100": page(
                1, 1, [submission(151, score=0), submission(152, score=0)], 2
            ),
        }

        with mock.patch.object(samcoding_uz.REQ, "get", side_effect=lambda url, **kwargs: responses[url]):
            standings = samcoding_uz.Statistic(contest=self.contest).get_standings()

        parsed_row = standings["result"]["coder"]
        assert standings["standings_kind"] == "icpc"
        assert parsed_row["solving"] == 1
        assert parsed_row["penalty"] == 29
        assert parsed_row["problems"]["A"]["result"] == "+1"
        assert parsed_row["problems"]["A"]["time"] == "0:09"
        assert parsed_row["problems"]["A"]["submission_id"] == 152
        assert parsed_row["problems"]["B"] == {"result": "-3"}

    def test_invalid_page_does_not_advance_submission_cursor(self):
        responses = {
            CONTEST_URL: self.contest_data,
            CONTEST_URL + "clist-standings/": self.clist_data,
            CONTEST_URL + "standings/?page=1": page(1, 1, [self.row]),
            CONTEST_URL + "submissions/?page=1&pageSize=1": page(1, 201, [submission(1)], 201),
            CONTEST_URL + "submissions/?page=201&pageSize=1": page(201, 201, [submission(201)], 201),
            CONTEST_URL + "submissions/?page=3&pageSize=100": page(3, 3, [submission(201)], 201),
            CONTEST_URL + "submissions/?page=2&pageSize=100": {"detail": "error"},
        }

        with (
            mock.patch.object(samcoding_uz.REQ, "get", side_effect=lambda url, **kwargs: responses[url]),
            pytest.raises(ExceptionParseStandings),
        ):
            samcoding_uz.Statistic(contest=self.contest).get_standings()

        assert self.contest.submissions_info == {"last_submission_id": 150, "count": 10, "upsolving_version": 1}

    def test_profile(self):
        profile = {
            "username": "coder",
            "first_name": "Code",
            "last_name": "Writer",
            "avatar": "https://samcoding.uz/avatar.jpg",
            "country": "UZ",
            "city": "Navoiy",
            "school": "School",
            "rating": {"rating": 1990, "max_rating": 2000, "rating_name": "Candidate Master"},
        }
        history = [
            {"contest": "Initial rating", "rank": None, "rating": 1600, "change": 0},
            {"contest": "SamCoding Round 6 (Div. 3)", "rank": 4, "rating": 1990, "change": 10},
        ]
        with mock.patch.object(samcoding_uz.REQ, "get", side_effect=[profile, history]) as request_get:
            infos = list(samcoding_uz.Statistic.get_users_infos(["coder"], None, None))

        assert [call.args[0] for call in request_get.call_args_list] == [
            "https://samcoding.uz/api/users/coder/",
            "https://samcoding.uz/profile/coder/rating-history",
        ]
        assert all(call.kwargs["headers"]["Accept-Language"] == "en" for call in request_get.call_args_list)
        assert infos == [
            {
                "canonical_key": "coder",
                "info": {
                    "name": "Code Writer",
                    "avatar": "https://samcoding.uz/avatar.jpg",
                    "country": "UZ",
                    "city": "Navoiy",
                    "school": "School",
                    "first_name": "Code",
                    "last_name": "Writer",
                    "rating": 1990,
                    "max_rating": 2000,
                    "rating_name": "Candidate Master",
                },
                "contest_addition_update_params": {
                    "update": {
                        "SamCoding Round 6 (Div. 3)": {
                            "old_rating": 1980,
                            "rating_change": 10,
                            "new_rating": 1990,
                        }
                    },
                    "by": "title",
                    "clear_rating_change": True,
                },
            }
        ]

    def test_upcoming_contest_skips_unavailable_standings(self):
        with mock.patch.object(
            samcoding_uz.REQ, "get", return_value={"status": "upcoming", "problems": []}
        ) as request_get:
            standings = samcoding_uz.Statistic(contest=self.contest).get_standings()

        assert standings == {"action": "skip"}
        request_get.assert_called_once()


class SamcodingAccountSubmissionsTest(TestCase):
    def setUp(self):
        with mock.patch.object(Resource, "update_icon"):
            self.resource = Resource.objects.create(
                host="samcoding.uz", url="https://samcoding.uz/", enable=True, has_upsolving=True
            )
        self.account = Account.objects.create(resource=self.resource, key="coder")
        self.contest = Contest.objects.create(
            resource=self.resource,
            key="16",
            title="Round 6",
            host=self.resource.host,
            standings_kind="icpc",
            url="https://samcoding.uz/contests/16",
            start_time=datetime(2026, 9, 13, 14, 30, tzinfo=UTC),
            end_time=datetime(2026, 9, 13, 17, tzinfo=UTC),
            info={"problems": [{"short": "A", "name": "Task A", "full_score": 500}, {"short": "B", "name": "Task B"}]},
        )
        self.problem_data = {"uid": "task-a", "url": "https://samcoding.uz/problems/16/A"}
        self.item = {
            "id": 151,
            "username": "coder",
            "problem_uid": "task-a",
            "problem_title": "Task A",
            "contest_id": 16,
            "status": "Accepted",
            "created_at": "2026-09-14T12:00:00+05:00",
            "language_name": "Python 3.12",
            "time_used": 25,
            "memory_used": 1024,
        }

    def update_submissions(self, *pages, with_submissions=False, before_response=None, contest_data=None):
        responses = {
            f"{samcoding_uz.API_URL}submissions/?user=coder&page={number}&pageSize=100": page(
                number, len(pages), rows, total=sum(map(len, pages))
            )
            for number, rows in enumerate(pages, 1)
        }
        responses[f"{samcoding_uz.API_URL}problems/task-a/"] = self.problem_data
        responses[f"{samcoding_uz.API_URL}problems/task-b/"] = {
            "uid": "task-b",
            "url": "https://samcoding.uz/problems/16/B",
        }
        responses[CONTEST_URL] = contest_data

        def get_response(url, **kwargs):
            if before_response:
                before_response(url)
            response = responses[url]
            if isinstance(response, Exception):
                raise response
            return response

        with mock.patch.object(samcoding_uz.REQ, "get", side_effect=get_response) as request_get:
            ret = samcoding_uz.Statistic.update_submissions(
                self.account, self.resource, with_submissions=with_submissions
            )
        self.request_get = request_get
        self.account.refresh_from_db()
        return ret

    def add_statistic(self, problem, **kwargs):
        return Statistics.objects.create(
            resource=self.resource,
            contest=self.contest,
            account=self.account,
            addition={"problems": {"A": problem}},
            **kwargs,
        )

    def test_archive_submission_is_mapped_by_uid_without_contest_id(self):
        ret = self.update_submissions([self.item | {"contest_id": None, "problem_title": "Old title"}])

        statistic = self.account.statistics_set.get()
        assert statistic.contest == self.contest
        assert statistic.skip_in_stats
        assert statistic.addition["problems"]["A"]["upsolving"] == {
            "result": "+",
            "verdict": "AC",
            "verdict_full": "Accepted",
            "submission_id": 151,
            "submission_time": datetime(2026, 9, 14, 7, tzinfo=UTC).timestamp(),
            "language": "Python 3.12",
            "exec_time": "25 ms",
            "memory_usage": "1024 KB",
        }
        assert self.account.last_submission == datetime(2026, 9, 14, 7, tzinfo=UTC)
        assert self.account.n_contests == 0
        assert self.account.n_upsolved == 1
        assert self.account.submissions_info == {"last_submission_id": 151, "count": 1}
        assert ret["n_updated"] == 1
        assert "submissions" not in ret

    def test_pagination_stops_at_saved_cursor_and_caches_problems(self):
        self.account.submissions_info = {"last_submission_id": 150, "count": 10}
        self.account.save(update_fields=["submissions_info"])
        self.update_submissions(
            [self.item | {"id": 202}, self.item | {"id": 201, "problem_uid": "task-b"}],
            [self.item, self.item | {"id": 150}],
            [self.item | {"id": 149}],
        )

        urls = [call.args[0] for call in self.request_get.call_args_list]
        assert len(urls) == 4
        assert not any("page=3" in url for url in urls)
        assert self.account.submissions_info == {"last_submission_id": 202, "count": 13}
        assert self.account.n_upsolved == 2

    def test_unchanged_history_does_not_fetch_problems_or_update_statistics(self):
        self.update_submissions([self.item])
        ret = self.update_submissions([self.item])

        self.request_get.assert_called_once()
        assert ret["n_updated"] == 0
        assert self.account.submissions_info == {"last_submission_id": 151, "count": 1}
        assert self.account.n_upsolved == 1

    def test_existing_and_new_contest_statistics_update_account_totals(self):
        self.add_statistic({"result": "-1"})
        Contest.objects.create(
            resource=self.resource,
            key="17",
            title="Round 7",
            host=self.resource.host,
            url="https://samcoding.uz/contests/17",
            standings_kind="icpc",
            start_time=self.contest.start_time,
            end_time=self.contest.end_time,
            info={"problems": [{"short": "A", "name": "Task C", "full_score": 100}]},
        )
        self.account.refresh_from_db()
        responses = {
            f"{samcoding_uz.API_URL}submissions/?user=coder&page=1&pageSize=100": page(
                1, 1, [self.item | {"id": 152}, self.item | {"contest_id": 17, "problem_uid": "task-c"}], total=2
            ),
            f"{samcoding_uz.API_URL}problems/task-a/": self.problem_data,
            f"{samcoding_uz.API_URL}problems/task-c/": {"uid": "task-c", "url": "https://samcoding.uz/problems/17/A"},
        }
        with mock.patch.object(samcoding_uz.REQ, "get", side_effect=lambda url, **kwargs: responses[url]):
            ret = samcoding_uz.Statistic.update_submissions(self.account, self.resource)

        self.account.refresh_from_db()
        assert ret["n_contests"] == 2
        assert list(self.account.statistics_set.order_by("contest_id").values_list("n_upsolved", flat=True)) == [1, 1]
        assert self.account.n_upsolved == 2
        assert self.account.total_solving == 2
        assert self.account.last_submission == datetime(2026, 9, 14, 7, tzinfo=UTC)
        assert self.account.submissions_info == {"last_submission_id": 152, "count": 2}

    def test_newer_failed_submission_does_not_hide_accepted_submission(self):
        self.update_submissions([
            self.item | {"id": 152, "status": "Wrong Answer #2"},
            self.item,
        ])

        problem = self.account.statistics_set.get().addition["problems"]["A"]
        assert problem["upsolving"]["submission_id"] == 151
        assert problem["upsolving"]["result"] == "+"
        assert self.account.n_upsolved == 1

    def test_failed_submission_keeps_verdict_and_test(self):
        self.update_submissions([self.item | {"status": "Wrong Answer #2"}])

        upsolving = self.account.statistics_set.get().addition["problems"]["A"]["upsolving"]
        assert upsolving["result"] == "-"
        assert upsolving["verdict"] == "WA"
        assert upsolving["test"] == 2

    def test_contest_result_and_partial_upsolving_are_preserved(self):
        self.contest.standings_kind = "scoring"
        self.contest.save(update_fields=["standings_kind"])
        original = {"result": 200, "partial": True, "upsolving": {"result": 300, "partial": True, "submission_id": 140}}
        statistic = self.add_statistic(original, solving=200)
        self.update_submissions([self.item | {"status": "Wrong Answer #3"}])

        statistic.refresh_from_db()
        assert statistic.addition["problems"]["A"] == original

        self.update_submissions([self.item | {"id": 152}])
        statistic.refresh_from_db()
        problem = statistic.addition["problems"]["A"]
        assert problem["result"] == 200
        assert problem["partial"]
        assert problem["upsolving"]["result"] == 500
        assert "partial" not in problem["upsolving"]
        assert statistic.upsolving == 300
        assert statistic.total_solving == 500
        assert self.account.total_solving == 500

    def test_ioi_full_score_is_not_replaced_with_binary_result(self):
        self.contest.standings_kind = "scoring"
        self.contest.save(update_fields=["standings_kind"])
        statistic = self.add_statistic(
            {"result": 200, "partial": True, "upsolving": {"result": 500, "submission_id": 140}}, solving=200
        )
        self.update_submissions([self.item])

        statistic.refresh_from_db()
        assert statistic.addition["problems"]["A"]["upsolving"]["result"] == 500
        assert statistic.total_solving == 500
        assert self.account.total_solving == 500

    def test_ioi_rejection_does_not_claim_a_full_solution(self):
        self.contest.standings_kind = "scoring"
        self.contest.save(update_fields=["standings_kind"])
        self.update_submissions([self.item | {"status": "Wrong Answer #2"}])

        statistic = self.account.statistics_set.get()
        upsolving = statistic.addition["problems"]["A"]["upsolving"]
        assert upsolving["result"] == 0
        assert upsolving["partial"]
        assert statistic.n_upsolved == 0
        assert not self.account.n_upsolved

    def test_unknown_contest_format_is_fetched_once(self):
        self.contest.standings_kind = None
        self.contest.save(update_fields=["standings_kind"])
        self.update_submissions([self.item | {"id": 152}, self.item], contest_data={"format_type": "ioi"})

        assert sum(call.args[0] == CONTEST_URL for call in self.request_get.call_args_list) == 1
        statistic = self.account.statistics_set.get()
        assert statistic.addition["problems"]["A"]["upsolving"]["result"] == 500

    def test_unknown_api_format_does_not_advance_cursor(self):
        self.contest.standings_kind = None
        self.contest.save(update_fields=["standings_kind"])
        with pytest.raises(ExceptionParseAccounts, match="Unexpected contest format"):
            self.update_submissions([self.item], contest_data={"format_type": "unknown"})

        self.account.refresh_from_db()
        assert self.account.submissions_info == {}
        assert not self.account.statistics_set.exists()

    def test_missing_ioi_full_score_does_not_advance_cursor(self):
        self.contest.standings_kind = "scoring"
        self.contest.save(update_fields=["standings_kind"])
        with pytest.raises(ExceptionParseAccounts, match="Missing full score"):
            self.update_submissions([self.item | {"problem_uid": "task-b"}])

        self.account.refresh_from_db()
        assert self.account.submissions_info == {}
        assert not self.account.statistics_set.exists()

    def test_standings_updated_during_pagination_are_preserved(self):
        statistic = self.add_statistic({"result": "-1"}, place="2", solving=0)
        latest = {
            "new_rating": 1800,
            "problems": {"A": {"result": "+", "first_ac": True}, "B": {"result": "-2"}},
        }

        def update_standings(url):
            if "page=2&" in url:
                Statistics.objects.filter(pk=statistic.pk).update(place="1", solving=1, addition=latest)

        self.update_submissions(
            [self.item | {"id": 152}],
            [self.item | {"problem_uid": "task-b"}],
            before_response=update_standings,
        )

        statistic.refresh_from_db()
        assert statistic.place == "1"
        assert statistic.solving == 1
        assert statistic.addition["new_rating"] == 1800
        assert statistic.addition["problems"]["A"] == latest["problems"]["A"]
        assert statistic.addition["problems"]["B"]["result"] == "-2"
        assert statistic.addition["problems"]["B"]["upsolving"]["result"] == "+"
        assert statistic.total_solving == 2

    def test_upsolving_updated_during_pagination_is_preserved(self):
        statistic = self.add_statistic({"result": "-1"})
        latest = {"result": "+", "submission_id": 200, "submission_time": 2_000_000_000}

        def update_standings(url):
            if "page=2&" in url:
                Statistics.objects.filter(pk=statistic.pk).update(
                    addition={"problems": {"A": {"result": "-1", "upsolving": latest}}}
                )

        self.update_submissions([self.item | {"id": 152}], [self.item], before_response=update_standings)

        statistic.refresh_from_db()
        assert statistic.addition["problems"]["A"]["upsolving"] == latest

    def test_notifications_include_non_improving_submissions_in_api_order(self):
        self.add_statistic({"result": "+"})
        ret = self.update_submissions(
            [self.item | {"id": 152, "status": "Wrong Answer #2"}, self.item], with_submissions=True
        )

        assert ret["n_updated"] == 0
        assert [s["info"]["submission_id"] for s in ret["submissions"]] == [152, 151]
        assert [s["info"]["verdict"] for s in ret["submissions"]] == ["WA", "AC"]
        assert all(s["contest"] == self.contest for s in ret["submissions"])
        assert all(s["problem"] == next(self.contest.problems_list) for s in ret["submissions"])
        self.resource.profile_url = "https://samcoding.uz/profile/{account}"
        message = compose_message_by_submissions(self.resource, self.account, ret["submissions"])
        assert "Task A" in message
        assert "`WA`" in message
        assert "`AC`" in message

        ret = self.update_submissions([self.item | {"id": 152}, self.item], with_submissions=True)
        assert not ret.get("submissions")

    def test_notifications_wait_until_pending_submission_is_judged(self):
        ret = self.update_submissions([self.item | {"status": "Running"}], with_submissions=True)
        assert not ret.get("submissions")

        ret = self.update_submissions([self.item], with_submissions=True)
        assert len(ret["submissions"]) == 1
        assert ret["submissions"][0]["info"]["verdict"] == "AC"

        ret = self.update_submissions([self.item], with_submissions=True)
        assert not ret.get("submissions")

    def test_problem_solved_during_contest_is_not_upsolved(self):
        statistic = self.add_statistic({"result": "+"})
        ret = self.update_submissions([self.item])

        statistic.refresh_from_db()
        assert statistic.addition["problems"]["A"] == {"result": "+"}
        assert ret["n_updated"] == 0

    def test_submissions_before_contest_end_are_ignored(self):
        self.update_submissions([
            self.item | {"id": 152, "created_at": "2026-09-13T21:59:59+05:00"},
            self.item | {"contest_id": None, "created_at": "2026-09-12T12:00:00+05:00"},
        ])

        assert not self.account.statistics_set.exists()
        assert self.account.submissions_info == {"last_submission_id": 152, "count": 2}

    def test_pending_submission_is_retried_without_new_submissions(self):
        pending = self.item | {"status": "Running", "time_used": None, "memory_used": None}
        self.update_submissions([pending])
        self.update_submissions([pending])

        assert not self.account.statistics_set.exists()
        assert self.account.submissions_info == {"last_submission_id": 151, "count": 1, "pending_submission_ids": [151]}

        self.update_submissions([self.item])

        assert self.account.statistics_set.get().addition["problems"]["A"]["upsolving"]["result"] == "+"
        assert self.account.submissions_info == {"last_submission_id": 151, "count": 1}

    def test_pending_submission_on_older_page_is_retried(self):
        self.account.submissions_info = {"last_submission_id": 202, "count": 10, "pending_submission_ids": [151]}
        self.account.save(update_fields=["submissions_info"])

        self.update_submissions([self.item | {"id": 202}], [self.item], [self.item | {"id": 100}])

        assert self.account.statistics_set.get().addition["problems"]["A"]["upsolving"]["submission_id"] == 151
        assert self.account.submissions_info == {"last_submission_id": 202, "count": 10}
        assert self.request_get.call_count == 3

    def test_missing_contest_or_problem_does_not_create_statistics(self):
        self.problem_data = FailOnGetResponse(SimpleNamespace(code=404))
        ret = self.update_submissions([self.item | {"id": 152, "contest_id": 999}, self.item])

        assert not self.account.statistics_set.exists()
        assert ret["missing_contests"] == 1
        assert ret["missing_problems"] == 1
        assert self.account.submissions_info == {"last_submission_id": 152, "count": 2}

    def test_invalid_later_page_rolls_back_statistics_and_cursor(self):
        with pytest.raises(ExceptionParseAccounts, match="out of order"):
            self.update_submissions([self.item], [self.item | {"id": 152}])

        self.account.refresh_from_db()
        assert self.account.submissions_info == {}
        assert self.account.last_submission is None
        assert not self.account.statistics_set.exists()

    def test_empty_history(self):
        ret = self.update_submissions([])

        assert ret["n_updated"] == 0
        assert self.account.submissions_info == {"last_submission_id": -1, "count": 0}
        assert not self.account.statistics_set.exists()
