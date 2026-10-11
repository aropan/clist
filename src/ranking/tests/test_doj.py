import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

import pytest
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from clist.models import Contest, Resource
from ranking.management.commands.parse_statistic import Command
from ranking.management.modules import doj
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse
from ranking.models import Account, Module, Statistics
from ranking.utils import account_update_contest_additions
from ranking.views import get_standings_fields


def scoreboard_page(data):
    flight = '1:I[123]\n2:["$","$L1",null,' + json.dumps(data) + "]\n"
    split = len(flight) // 2
    return "".join(
        f"<script>self.__next_f.push({json.dumps([1, chunk])})</script>" for chunk in (flight[:split], flight[split:])
    )


class DojParserTests(SimpleTestCase):
    def setUp(self):
        self.parser = doj.Statistic(key="round", url="https://doj.kr/en/contests/round")
        self.contest = {"ratingEligible": True, "status": "ENDED"}
        self.participations = {
            "participations": [
                {
                    "contest": {"slug": "round"},
                    "ratingBefore": 1200,
                    "ratingAfter": 1200,
                    "ratingDelta": 0,
                    "ratedPerformance": 1200,
                    "isUnofficial": False,
                },
            ],
            "nextCursor": None,
        }
        self.team = {
            "id": "team-id",
            "name": "Choi's Team",
            "members": [{"user": {"handle": handle}} for handle in ("rladbeka", "guu", "woohyunjng")],
        }
        self.scoreboard = {
            "scoreboardVisible": True,
            "scoringMode": "DOJ",
            "problems": [
                {
                    "id": "problem-id",
                    "shortLabel": "A",
                    "title": "BCD Operation",
                    "subtitle": "bcd",
                    "maxScore": 100,
                    "href": "/en/problems/627?contest=contest-id",
                },
            ],
            "rows": [
                {
                    "displayName": "Handle",
                    "userId": "internal-user-id",
                    "rank": 1,
                    "totalScore": 53,
                    "penaltySeconds": 10429,
                    "performance": 2834,
                    "ratingDelta": 0,
                    "isRatingPreview": False,
                    "cells": [
                        {
                            "problemId": "problem-id",
                            "score": 53,
                            "maxScore": 100,
                            "wrongAttempts": 2,
                            "acceptedAtSeconds": None,
                            "pendingCount": 0,
                            "isFirstSolve": False,
                        },
                    ],
                },
            ],
        }

    def api(self, path):
        if path == "contests/round":
            return {"contest": self.contest}
        if path == "problems/627":
            return {"problem": {"titles": {"en": "BCD Operation"}, "difficulty": 4, "tags": ["math"]}}
        raise AssertionError(f"Unexpected API request: {path}")

    def parse(self, **kwargs):
        def get_page(url):
            if url == "https://doj.kr/en/teams/choisteam":
                return scoreboard_page({"team": self.team})
            assert url == "https://doj.kr/en/contests/round/standings"
            return scoreboard_page(self.scoreboard)

        with (
            patch.object(doj.Statistic, "_get_api", side_effect=self.api),
            patch.object(doj.REQ, "get", side_effect=get_page),
        ):
            return self.parser.get_standings(**kwargs)

    def make_team_row(self):
        self.scoreboard["rows"][0].update(displayName="choisteam", profileHref="/en/teams/choisteam")

    def test_team_results_are_copied_to_each_member_without_individual_ratings(self):
        self.make_team_row()
        standings = self.parse()
        assert standings["grouped_team"] is True
        result = standings["result"]
        members = ["rladbeka", "guu", "woohyunjng"]
        assert list(result) == members
        for handle, row in result.items():
            assert row["member"] == handle
            assert row["team_id"] == "team-id"
            assert row["name"] == "Choi's Team"
            assert row["_members"] == [{"account": member} for member in members]
            assert row["_account_url"] == "https://doj.kr/en/teams/choisteam"
            assert row["place"] == 1
            assert row["solving"] == 53
            assert row["problems"] == {"A": {"result": 53, "partial": True}}
            for field in ("old_rating", "new_rating", "rating_change", "performance", "is_rated"):
                assert field not in row
        result["rladbeka"]["problems"]["A"]["result"] = 100
        assert result["guu"]["problems"]["A"]["result"] == 53

    def test_team_users_filter_matches_members_and_keeps_complete_roster(self):
        self.make_team_row()
        result = self.parse(users=["guu"])["result"]
        assert list(result) == ["guu"]
        assert result["guu"]["_members"] == [{"account": handle} for handle in ("rladbeka", "guu", "woohyunjng")]
        assert self.parse(users=["choisteam"])["result"] == {}
        assert self.parse(users=[])["result"] == {}
        assert self.parse(users=[])["grouped_team"] is True

    def test_team_and_individual_results_can_share_a_scoreboard(self):
        individual = deepcopy(self.scoreboard["rows"][0])
        self.make_team_row()
        self.scoreboard["rows"].append(individual)
        result = self.parse()["result"]
        assert len(result) == 4
        assert result["guu"]["team_id"] == "team-id"
        assert "team_id" not in result["Handle"]
        assert result["Handle"]["performance"] == 2834
        assert result["Handle"]["rating_change"] == 0

    def test_organization_label_does_not_make_an_individual_a_team(self):
        self.scoreboard["rows"][0].update(profileHref="/en/user/internal-user-id", teamLabel="School")
        result = self.parse()["result"]
        assert list(result) == ["Handle"]
        assert result["Handle"]["info"] == {"organization": "School"}
        assert "team_id" not in result["Handle"]

    def test_missing_team_data_is_an_error(self):
        self.make_team_row()
        for team in (None, {}, dict(self.team, members=[])):
            self.team = team
            with self.subTest(team=team), self.assertRaisesMessage(ExceptionParseStandings, "DOJ team data not found"):
                self.parse()

    def test_scoring_partial_scores_rating_and_public_problem_code(self):
        standings = self.parse()
        assert standings["grouped_team"] is False
        row = standings["result"]["Handle"]
        assert row["problems"] == {"A": {"result": 53, "partial": True}}
        assert row["penalty"] == "2:53:49"
        assert row["solved"] == {"solving": 0}
        assert "old_rating" not in row
        assert "new_rating" not in row
        assert row["rating_change"] == 0
        assert row["performance"] == 2834
        assert standings["problems"][0]["code"] == "627"
        assert standings["problems"][0]["difficulty"] == 4
        assert standings["standings_kind"] == "scoring"

    def test_icpc_attempts_first_solve_and_elapsed_time(self):
        self.scoreboard["scoringMode"] = "ICPC"
        cell = self.scoreboard["rows"][0]["cells"][0]
        cell.update(score=1, maxScore=1, acceptedAtSeconds=120, isFirstSolve=True)
        standings = self.parse()
        row = standings["result"]["Handle"]
        assert row["problems"]["A"] == {
            "result": "+2",
            "time": "0:02:00",
            "time_in_seconds": 120,
            "first_ac": True,
        }
        assert row["solved"] == {"solving": 1}
        assert "full_score" not in standings["problems"][0]
        assert standings["standings_kind"] == "icpc"

    def test_icpc_unsolved_pending_and_unattempted(self):
        self.contest["ratingEligible"] = False
        self.scoreboard["scoringMode"] = "ICPC"
        cell = self.scoreboard["rows"][0]["cells"][0]
        cell.update(score=0, maxScore=1)
        assert self.parse()["result"]["Handle"]["problems"]["A"]["result"] == "-2"
        cell.update(wrongAttempts=0, pendingCount=1)
        assert self.parse()["result"]["Handle"]["problems"]["A"]["result"] == "?1"
        cell["pendingCount"] = 0
        assert self.parse()["result"]["Handle"]["problems"] == {}

    def test_scoring_unattempted_pending_failed_and_zero_time_cells(self):
        self.contest["ratingEligible"] = False
        cell = self.scoreboard["rows"][0]["cells"][0]
        cell.update(score=0, wrongAttempts=0)
        assert self.parse()["result"]["Handle"]["problems"] == {}

        cell["pendingCount"] = 2
        assert self.parse()["result"]["Handle"]["problems"] == {"A": {"result": "?2"}}

        cell.update(pendingCount=0, wrongAttempts=1)
        assert self.parse()["result"]["Handle"]["problems"] == {"A": {"result": 0}}

        cell.update(wrongAttempts=0, acceptedAtSeconds=0)
        assert self.parse()["result"]["Handle"]["problems"] == {
            "A": {"result": 0, "time_in_seconds": 0, "time": "0:00:00"}
        }

        cell.update(score=100, acceptedAtSeconds=None, pendingCount=1)
        row = self.parse()["result"]["Handle"]
        assert row["problems"] == {"A": {"result": 100}}
        assert row["solved"] == {"solving": 1}

    def test_hidden_scoreboard_is_not_empty_success(self):
        self.scoreboard["scoreboardVisible"] = False
        with self.assertRaisesMessage(ExceptionParseStandings, "scoreboard is hidden"):
            self.parse()

    def test_missing_scoreboard_is_error(self):
        with self.assertRaisesMessage(ExceptionParseStandings, "scoreboard data not found"):
            doj.Statistic._get_scoreboard("<html>Unavailable</html>")

    def test_users_filter(self):
        assert self.parse(users=["SomeoneElse"])["result"] == {}

    def test_rating_previews_and_predictions_are_not_stored(self):
        for status in ("RUNNING", "ENDED"):
            for preview, prediction in ((True, False), (False, True), (True, True)):
                with self.subTest(status=status, preview=preview, prediction=prediction):
                    self.contest["status"] = status
                    self.scoreboard["rows"][0].update(
                        isRatingPreview=preview, isRatingPrediction=prediction, ratingDelta=152
                    )
                    row = self.parse()["result"]["Handle"]
                    assert "rating_change" not in row
                    assert "performance" not in row
                    assert row["solving"] == 53

    def test_final_ratings_accept_false_or_missing_prediction_flags(self):
        for flags in ({}, {"isRatingPreview": False}, {"isRatingPreview": False, "isRatingPrediction": False}):
            with self.subTest(flags=flags):
                data = self.scoreboard["rows"][0]
                data.pop("isRatingPreview", None)
                data.pop("isRatingPrediction", None)
                data.update(flags)
                data["ratingDelta"] = -10
                row = self.parse()["result"]["Handle"]
                assert row["rating_change"] == -10
                assert row["performance"] == 2834

    def test_standings_preserves_ratings_received_from_profiles(self):
        self.scoreboard["rows"][0].update(performance=None, ratingDelta=None)
        previous = {
            "old_rating": 1200,
            "new_rating": 1200,
            "rating_change": 0,
            "performance": 1200,
            "is_rated": True,
            "unofficial": False,
        }
        row = self.parse(statistics={"Handle": previous})["result"]["Handle"]
        for field, value in previous.items():
            assert row[field] == value

    def test_standings_requests_do_not_depend_on_individual_participant_count(self):
        self.scoreboard["rows"] = [
            dict(deepcopy(self.scoreboard["rows"][0]), displayName=f"Handle{i}") for i in range(100)
        ]
        with (
            patch.object(self, "api", wraps=self.api) as api,
            patch.object(doj.Statistic, "_get_pages") as get_pages,
        ):
            result = self.parse()["result"]
        assert len(result) == 100
        assert [call.args[0] for call in api.call_args_list] == ["contests/round", "problems/627"]
        get_pages.assert_not_called()

    def test_pagination_preserves_opaque_cursor(self):
        with patch.object(
            doj.Statistic,
            "_get_api",
            side_effect=[{"points": [1], "nextCursor": "a+/="}, {"points": [2], "nextCursor": None}],
        ) as get:
            assert list(doj.Statistic._get_pages("users/Handle/rating-history", "points")) == [1, 2]
        assert get.call_args_list[-1].args == ("users/Handle/rating-history?limit=200&cursor=a%2B%2F%3D",)

    def test_repeated_cursor_and_invalid_response_are_errors(self):
        with (
            patch.object(doj.Statistic, "_get_api", return_value={"points": [], "nextCursor": "repeated"}),
            self.assertRaisesMessage(ExceptionParseStandings, "Repeated DOJ"),
        ):
            list(doj.Statistic._get_pages("users/Handle/rating-history", "points"))
        with (
            patch.object(doj.Statistic, "_get_api", return_value={"error": "api_unavailable"}),
            self.assertRaisesMessage(ExceptionParseStandings, "Invalid DOJ"),
        ):
            list(doj.Statistic._get_pages("users/Handle/rating-history", "points"))

    def test_profiles_and_paginated_rating_history_keep_case_and_skip_private_contests(self):
        responses = [
            {
                "user": {
                    "handle": "Handle",
                    "rating": 1432,
                    "countryCode": "KR",
                    "organization": None,
                    "avatarUrl": "/api/storage-assets/avatar",
                    "contestsCount": 2,
                }
            },
            self.participations,
            {
                "points": [
                    {"contest": None, "kind": "CONTEST", "oldRating": 1200, "newRating": 1402, "delta": 202},
                ],
                "nextCursor": "opaque",
            },
            {
                "points": [
                    {
                        "contest": {"slug": "round"},
                        "kind": "CONTEST",
                        "oldRating": 1402,
                        "newRating": 1432,
                        "delta": 30,
                    },
                ],
                "nextCursor": None,
            },
        ]
        with patch.object(doj.Statistic, "_get_api", side_effect=responses) as get:
            (ret,) = doj.Statistic.get_users_infos(["Handle"], SimpleNamespace(url="https://doj.kr"), [])
        assert get.call_args_list[0].args == ("users/Handle",)
        assert ret["canonical_key"] == "Handle"
        assert ret["info"]["country"] == "KR"
        assert ret["info"]["avatar"] == "https://doj.kr/api/storage-assets/avatar"
        assert ret["contest_addition_update_params"] == {
            "by": "key",
            "hidden_fields": ["unofficial", "is_rated"],
            "update": {
                "round": {
                    "old_rating": 1402,
                    "new_rating": 1432,
                    "rating_change": 30,
                    "performance": 1200,
                    "is_rated": True,
                    "unofficial": False,
                }
            },
        }

    def test_unrated_participations_update_flags_through_profiles(self):
        participation = self.participations["participations"][0]
        participation.update(
            ratingBefore=None, ratingAfter=None, ratingDelta=None, ratedPerformance=None, isUnofficial=True
        )
        responses = [
            {"user": {"handle": "Handle", "rating": 1200}},
            self.participations,
            {"points": [], "nextCursor": None},
        ]
        with patch.object(doj.Statistic, "_get_api", side_effect=responses):
            (ret,) = doj.Statistic.get_users_infos(["Handle"], SimpleNamespace(url="https://doj.kr"), [])
        assert ret["contest_addition_update_params"] == {
            "by": "key",
            "hidden_fields": ["unofficial", "is_rated"],
            "update": {"round": {"is_rated": False, "unofficial": True}},
        }

    def test_profile_not_found_and_temporary_failure(self):
        for code, expected in ((404, "delete"), (503, "skip")):
            error = FailOnGetResponse(SimpleNamespace(code=code))
            with patch.object(doj.Statistic, "_get_api", side_effect=error):
                (ret,) = doj.Statistic.get_users_infos(["Handle"], object(), [])
            assert ret[expected] is True

    def test_history_failures_skip_only_the_affected_user(self):
        participation = self.participations
        history = {
            "points": [
                {"contest": {"slug": "round"}, "kind": "CONTEST", "oldRating": 1200, "newRating": 1300, "delta": 100}
            ],
            "nextCursor": "opaque",
        }
        for endpoint in ("contest-participations", "rating-history"):
            for code in (404, 503):
                for later_page in (False, True):
                    with self.subTest(endpoint=endpoint, code=code, later_page=later_page):
                        responses = [{"user": {"handle": "Handle", "rating": 1300}}]
                        if endpoint == "rating-history":
                            responses.append(participation)
                        if later_page:
                            page = (
                                dict(participation, nextCursor="opaque")
                                if endpoint == "contest-participations"
                                else history
                            )
                            responses.append(page)
                        responses.append(FailOnGetResponse(SimpleNamespace(code=code)))
                        responses.extend([
                            {"user": {"handle": "Next", "rating": 1200}},
                            {"participations": [], "nextCursor": None},
                            {"points": [], "nextCursor": None},
                        ])
                        pbar = Mock()
                        with patch.object(doj.Statistic, "_get_api", side_effect=responses) as get:
                            failed, following = doj.Statistic.get_users_infos(
                                ["Handle", "Next"], SimpleNamespace(url="https://doj.kr"), [], pbar=pbar
                            )
                        assert failed == {"skip": True, "delta": timedelta(days=1)}
                        assert following["canonical_key"] == "Next"
                        assert following["info"]["rating"] == 1200
                        assert following["contest_addition_update_params"]["update"] == {}
                        assert get.call_count == len(responses)
                        assert pbar.update.call_count == 2

    def test_problem_not_public_is_allowed_but_api_failure_is_not(self):
        response = SimpleNamespace(code=404)
        error = FailOnGetResponse(response)

        def api(path):
            if path == "problems/627":
                raise error
            return self.api(path)

        with (
            patch.object(doj.Statistic, "_get_api", side_effect=api),
            patch.object(doj.REQ, "get", return_value=scoreboard_page(self.scoreboard)),
        ):
            assert "difficulty" not in self.parser.get_standings()["problems"][0]
            response.code = 503
            with pytest.raises(FailOnGetResponse):
                self.parser.get_standings()


class DojProfileUpdateTests(TestCase):
    def setUp(self):
        self.resource = Resource(host="doj-profile.example", enable=True, url="https://doj.kr/")
        Resource.objects.bulk_create([self.resource])
        Module.objects.create(
            resource=self.resource,
            path="ranking.management.modules.doj",
            max_delay_after_end=timedelta(hours=1),
            delay_on_success=timedelta(minutes=10),
            delay_on_error=timedelta(minutes=10),
        )
        now = timezone.now()
        self.contest = Contest(
            resource=self.resource,
            title="DOJ profile update",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            duration_in_secs=3600,
            url="https://doj.kr/en/contests/round",
            key="round",
            host=self.resource.host,
            parsed_time=now,
        )
        Contest.objects.bulk_create([self.contest])

    def parse_standings(self):
        scoreboard = {
            "scoreboardVisible": True,
            "scoringMode": "DOJ",
            "problems": [],
            "rows": [{"displayName": "Handle", "rank": 1, "totalScore": 100, "penaltySeconds": 0, "cells": []}],
        }
        with (
            patch.object(
                Resource, "plugin", new_callable=PropertyMock, return_value=SimpleNamespace(Statistic=doj.Statistic)
            ),
            patch.object(
                doj.Statistic, "_get_api", return_value={"contest": {"ratingEligible": True, "status": "ENDED"}}
            ),
            patch.object(doj.REQ, "get", return_value=scoreboard_page(scoreboard)),
        ):
            Command().parse_statistic(
                Contest.objects.filter(pk=self.contest.pk), with_check=False, without_subscriptions=True
            )
        self.contest.refresh_from_db()
        self.account = Account.objects.get(resource=self.resource, key="Handle")

    def update_profile(self):
        responses = [
            {"user": {"handle": "Handle", "rating": 1200}},
            {
                "participations": [
                    {
                        "contest": {"slug": "round"},
                        "ratingBefore": 1200,
                        "ratingAfter": 1200,
                        "ratingDelta": 0,
                        "ratedPerformance": 1200,
                        "isUnofficial": False,
                    }
                ],
                "nextCursor": None,
            },
            {"points": [], "nextCursor": None},
        ]
        with patch.object(doj.Statistic, "_get_api", side_effect=responses):
            (ret,) = doj.Statistic.get_users_infos(["Handle"], self.resource, [self.account])
        params = ret["contest_addition_update_params"]
        updates = params.pop("update")
        account_update_contest_additions(self.account, updates, **params)
        self.contest.refresh_from_db()

    def test_profile_flags_are_hidden_after_first_standings_parse(self):
        self.parse_standings()
        assert "is_rated" not in self.contest.info["fields"]
        assert "unofficial" not in self.contest.info["fields"]

        self.update_profile()

        statistic = Statistics.objects.get(account=self.account, contest=self.contest)
        assert statistic.addition["is_rated"] is True
        assert statistic.addition["unofficial"] is False
        visible = get_standings_fields(self.contest, None, True)
        for field in ("is_rated", "unofficial"):
            assert field in self.contest.info["fields"]
            assert field in self.contest.info["hidden_fields"]
            assert field not in visible

    def test_profile_update_hides_existing_flags_when_values_have_not_changed(self):
        self.parse_standings()
        self.update_profile()
        self.contest.info["hidden_fields"] = ["penalty"]
        self.contest.save(update_fields=["info"])
        addition = Statistics.objects.get(account=self.account, contest=self.contest).addition

        self.update_profile()

        assert Statistics.objects.get(account=self.account, contest=self.contest).addition == addition
        assert "penalty" in self.contest.info["hidden_fields"]
        visible = get_standings_fields(self.contest, None, True)
        for field in ("is_rated", "unofficial"):
            assert self.contest.info["hidden_fields"].count(field) == 1
            assert field not in visible

        with self.assertNumQueries(2):
            self.update_profile()
        for field in ("is_rated", "unofficial"):
            assert self.contest.info["hidden_fields"].count(field) == 1

    def test_updates_without_hidden_fields_preserve_existing_visibility(self):
        self.parse_standings()
        account_update_contest_additions(self.account, {"round": {"is_rated": True, "unofficial": False}}, by="key")
        self.contest.refresh_from_db()

        visible = get_standings_fields(self.contest, None, True)
        for field in ("is_rated", "unofficial"):
            assert field in visible
