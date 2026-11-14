import json
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

import pytest
from django.test import SimpleTestCase, TestCase

from clist.models import Contest, Resource
from ranking.management.commands.parse_statistic import Command
from ranking.management.modules import repovive
from ranking.management.modules.excepts import ExceptionParseStandings
from ranking.models import Account, Module, Statistics
from ranking.utils import account_update_contest_additions
from utils.timetools import parse_datetime


def entry(member="692621bffc69f93918ad6023", **changes):
    return {
        "odId": member,
        "rank": 1,
        "userName": "Participant",
        "userPicture": "https://images.example/avatar.png",
        "country": "RU",
        "totalScore": 493,
        "problemsSolved": 1,
        "solvedProblems": ["A"],
        "problemScores": [
            {"letter": "A", "score": 493, "time": 4, "wrongs": 1},
            {"letter": "B", "score": -1, "time": 0, "wrongs": 2},
        ],
        "lastAcceptedAt": "2026-11-10T14:39:32.166Z",
        "ratingDelta": 0,
        "rating": 2042,
        "contestCount": 13,
        "identityMarks": {"admin": False, "mathRating": None, "contests": {"cp": 13, "math": 0}},
        **changes,
    }


def page(rows, number=1, total_pages=1, **changes):
    return {
        "rankings": rows,
        "problems": [
            {"letter": "A", "title": "Two-Coin Fee", "points": 500, "slug": "unused", "acceptedCount": 96},
            {"letter": "B", "title": "Single-Use Switches", "points": 1000},
        ],
        "pagination": {"page": number, "totalPages": total_pages},
        "scoringType": "codeforces",
        "rankingType": "contest",
        "contestDurationMinutes": 120,
        "ratingDeltaStatus": "projected",
        "countryFilter": None,
        "followingOnly": False,
        "totalParticipants": len(rows),
        "availableCountries": [{"code": "RU", "count": 1}],
        **changes,
    }


def profile_page(user, history=()):
    props = {"viewer": None, "user": user, "initialRatingHistory": list(history), "isOwnProfile": False}
    flight = '1:I[123,[],"default"]\n16:' + json.dumps(["$", "$L1", None, props]) + "\n"
    step = len(flight) // 3
    scripts = ["<script>self.__next_f.push([0])</script>"]
    for offset in range(0, len(flight), step):
        chunk = json.dumps([1, flight[offset : offset + step]])
        scripts.append(f'<script nonce="test">self.__next_f.push({chunk})</script>')
    return "".join(scripts)


class RepoviveTests(SimpleTestCase):
    def setUp(self):
        contest = Contest(
            resource=Resource(host="judge.example", info={"major_kinds": ["cp"]}),
            kind="cp",
            key="mongo-contest-id",
            url="https://judge.example:8443/contests/31",
            info={"parse": {"contestNumber": 31}},
            start_time=parse_datetime("2026-11-10T14:35:00Z"),
        )
        self.parser = repovive.Statistic(contest=contest)
        self.get = self.enterContext(mock.patch.object(repovive.REQ, "get"))

    def test_pagination_and_user_selection_preserve_official_rank(self):
        self.get.side_effect = [
            page([entry("first")], total_pages=2, totalParticipants=2),
            page([entry("second", rank=42)], number=2, total_pages=2, totalParticipants=2),
        ]
        standings = self.parser.get_standings(users=["second"])
        assert list(standings["result"]) == ["second"]
        row = standings["result"]["second"]
        assert row["place"] == 42
        assert row["solving"] == 493
        assert row["problems"]["A"]["result"] == 493
        assert self.get.call_count == 2

    def test_incomplete_pagination_is_rejected(self):
        rows = [entry(str(index), rank=index + 1) for index in range(100)]
        for last_page in ([], [entry("100", rank=101)]):
            with self.subTest(last_page_size=len(last_page)):
                self.get.side_effect = [
                    page(rows, total_pages=2, totalParticipants=102),
                    page(last_page, number=2, total_pages=2, totalParticipants=102),
                ]
                with pytest.raises(ExceptionParseStandings):
                    self.parser.get_standings()

    def test_changed_pagination_is_rejected(self):
        rows = [entry(str(index), rank=index + 1) for index in range(200)]
        self.get.side_effect = [
            page(rows[:100], total_pages=3, totalParticipants=201),
            page(rows[100:], number=2, total_pages=2, totalParticipants=201),
        ]
        with pytest.raises(ExceptionParseStandings, match="pagination changed"):
            self.parser.get_standings()

    def test_repeated_participant_is_rejected_even_when_not_selected(self):
        self.get.side_effect = [
            page([entry("unselected")], total_pages=2, totalParticipants=2),
            page([entry("unselected")], number=2, total_pages=2, totalParticipants=2),
        ]
        with pytest.raises(ExceptionParseStandings, match="Repeated"):
            self.parser.get_standings(users=["other"])


class RepoviveRatingUpdateTests(TestCase):
    def test_profile_ratings_survive_standings_refresh(self):
        resource = Resource(
            host="repovive-test.example",
            url="https://repovive-test.example/contests",
            enable=False,
            info={"major_kinds": ["cp"]},
        )
        Resource.objects.bulk_create([resource])
        account = Account(resource=resource, key="user")
        Account.objects.bulk_create([account])
        contest = Contest(
            resource=resource,
            host=resource.host,
            key="mongo-contest-id",
            title="Contest",
            kind="cp",
            url="https://repovive-test.example/contests/round-zero",
            start_time=parse_datetime("2020-01-01T00:00:00Z"),
            end_time=parse_datetime("2020-01-01T02:00:00Z"),
            duration_in_secs=7200,
            info={"parse": {"contestNumber": 0}},
        )
        Contest.objects.bulk_create([contest])
        stat = Statistics.objects.create(account=account, resource=resource, contest=contest)
        Module.objects.create(
            resource=resource,
            path="ranking.management.modules.repovive",
            max_delay_after_end=timedelta(days=30),
            delay_on_error=timedelta(hours=1),
            delay_on_success=timedelta(hours=8),
        )
        profile = profile_page(
            {"_id": "user", "rating": {"current": 0}},
            [{"contestNumber": 0, "rating": 0, "delta": 0, "performanceRating": 0, "rank": 2}],
        )
        with mock.patch.object(repovive.REQ, "get", return_value=profile):
            (ret,) = repovive.Statistic.get_users_infos(["user"], resource, [account])
        params = ret["contest_addition_update_params"]
        updates = params.pop("update")
        account_update_contest_additions(account, updates, **params)
        stat.refresh_from_db()
        assert stat.place_as_int == 2
        assert "_rank" not in stat.addition

        response = page([entry("user", rank=3, ratingDelta=999, userPicture=None)])
        with (
            mock.patch.object(
                Resource,
                "plugin",
                new_callable=mock.PropertyMock,
                return_value=SimpleNamespace(Statistic=repovive.Statistic),
            ),
            mock.patch.object(repovive.REQ, "get", return_value=response),
        ):
            Command().parse_statistic(
                Contest.objects.filter(pk=stat.contest_id),
                with_check=False,
                without_subscriptions=True,
                without_calculate_rating_prediction=True,
            )

        stat.refresh_from_db()
        expected = {"old_rating": 0, "new_rating": 0, "rating_change": 0, "performance": 0}
        assert {field: stat.addition[field] for field in expected} == expected
        assert stat.place_as_int == 3
        assert stat.solving == 493
        assert "_rank" not in stat.addition
