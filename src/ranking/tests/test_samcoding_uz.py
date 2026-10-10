from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

import pytest
from django.test import SimpleTestCase

from ranking.management.modules import samcoding_uz
from ranking.management.modules.excepts import ExceptionParseStandings

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
