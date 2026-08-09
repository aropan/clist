import os
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from django.utils.timezone import now

from ranking.management.modules.codeforces import REQ, Statistic


class CodeforcesStandingsTest(SimpleTestCase):
    def test_selected_user_ratings_are_assigned_to_matching_handles(self):
        current_time = now()
        contest = SimpleNamespace(
            pk=1,
            title="Codeforces test",
            url="https://codeforces.com/contests/1234",
            key="1234",
            standings_url=None,
            start_time=current_time - timedelta(days=2),
            end_time=current_time - timedelta(days=1),
            info={},
            resource=SimpleNamespace(),
            invisible=False,
            elimination_tournament_info=None,
        )
        rows = [
            {
                "party": {"participantType": "CONTESTANT", "members": [{"handle": handle}]},
                "rank": rank,
                "points": 0,
                "successfulHackCount": 0,
                "unsuccessfulHackCount": 0,
                "problemResults": [],
            }
            for rank, handle in enumerate(("alice", "bob", "unselected"), start=1)
        ]

        def api_query(method, **kwargs):
            if method == "contest.standings":
                return {
                    "status": "OK",
                    "result": {
                        "contest": {"phase": "FINISHED", "type": "CF", "durationSeconds": 7200},
                        "problems": [],
                        "rows": rows,
                    },
                }
            if method == "contest.status":
                return {"status": "OK", "result": []}
            raise AssertionError(f"unexpected API method: {method}")

        statistics = {
            "alice": {"old_rating": 100, "new_rating": 150},
            "bob": {"old_rating": 200, "new_rating": 250},
        }
        with mock.patch("ranking.management.modules.codeforces.api_query", side_effect=api_query):
            standings = Statistic(contest=contest).get_standings(
                users=["alice", "bob"],
                statistics=statistics,
            )

        assert standings["result"]["alice"]["old_rating"] == 100
        assert standings["result"]["alice"]["new_rating"] == 150
        assert standings["result"]["bob"]["old_rating"] == 200
        assert standings["result"]["bob"]["new_rating"] == 250
        assert "old_rating" not in standings["result"]["unselected"]


class CodeforcesUsersInfoTest(SimpleTestCase):
    def test_retries_after_missing_handle_response_without_result(self):
        responses = [
            {
                "status": "FAILED",
                "comment": "handles: User with handle missing_handle not found",
            },
            {
                "status": "OK",
                "result": [{"handle": "tourist"}],
            },
        ]

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("ranking.management.modules.codeforces.api_query", side_effect=responses) as api_query,
            mock.patch.object(REQ, "get") as request_get,
            mock.patch.object(REQ, "geturl", return_value="https://codeforces.com/"),
        ):
            infos = list(Statistic.get_users_infos(["missing_handle", "tourist"]))

        assert infos == [
            {"delete": True},
            {
                "info": {"handle": "tourist", "name": ""},
                "special_info_fields": {"name_ru"},
            },
        ]
        assert api_query.call_count == 2
        request_get.assert_not_called()
