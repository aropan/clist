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
            submissions_info={"last_submission_id": 150, "count": 10},
        )
        self.contest_data = {
            "format_type": "ioi",
            "problems": [{"letter": "A", "problem_title": "Task A", "url": "https://samcoding.uz/A", "score": 500}],
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

    def test_standings_and_new_submissions_only(self):
        responses = {
            CONTEST_URL: self.contest_data,
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

        assert request_get.call_count == 7
        requested_urls = [call.args[0] for call in request_get.call_args_list]
        assert CONTEST_URL + "submissions/?page=1&pageSize=100" not in requested_urls
        assert standings["submissions_info"] == {"last_submission_id": 202, "count": 13}
        assert self.contest.submissions_info == {"last_submission_id": 150, "count": 10}
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

    def test_submissions_outside_contest_do_not_enrich_problems(self):
        responses = {
            CONTEST_URL: self.contest_data,
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

    def test_unchanged_submissions_fetch_only_latest_record(self):
        responses = {
            CONTEST_URL: self.contest_data,
            CONTEST_URL + "standings/?page=1": page(1, 1, [self.row]),
            CONTEST_URL + "submissions/?page=1&pageSize=1": page(1, 150, [submission(1)], 150),
            CONTEST_URL + "submissions/?page=150&pageSize=1": page(150, 150, [submission(150)], 150),
        }

        with mock.patch.object(
            samcoding_uz.REQ, "get", side_effect=lambda url, **kwargs: responses[url]
        ) as request_get:
            standings = samcoding_uz.Statistic(contest=self.contest).get_standings()

        assert request_get.call_count == 4
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

        assert self.contest.submissions_info == {"last_submission_id": 150, "count": 10}

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
        assert infos == [
            {
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
