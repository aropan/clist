import json
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from django.utils.timezone import now

from ranking.management.modules.codingame import Statistic


class CodingameSelectedUsersTest(SimpleTestCase):
    def test_fetches_selected_users_by_public_handle(self):
        accounts = [
            SimpleNamespace(key="1", info={"profile_url": {"public_handle": "public-1"}}),
            SimpleNamespace(key="2", info={"profile_url": {"public_handle": "public-2"}}),
            SimpleNamespace(key="3", info={"profile_url": {"public_handle": "public-3"}}),
        ]
        account_set = mock.Mock()
        account_set.filter.return_value = accounts
        resource = SimpleNamespace(account_set=account_set)
        current_time = now()
        contest = SimpleNamespace(
            pk=1,
            title="Test challenge",
            url="https://www.codingame.com/contests/test-challenge",
            key="test-challenge",
            standings_url=None,
            start_time=current_time - timedelta(days=2),
            end_time=current_time - timedelta(days=1),
            info={},
            resource=resource,
            invisible=False,
        )
        leaderboard_requests = []

        def get(url, post=None, **kwargs):
            if url.endswith("services/Challenge/findWorldCupByPublicId"):
                return json.dumps({"challenge": {"type": "BATTLE"}})
            if url.endswith("services/Leaderboards/getFilteredChallengeLeaderboard"):
                payload = json.loads(post)
                public_handle = payload[1]
                leaderboard_requests.append(public_handle)
                if public_handle not in {"public-1", "public-2", "public-3"}:
                    raise AssertionError(f"unexpected full leaderboard request: {post}")
                user_id = public_handle.removeprefix("public-")
                user_ids = ["2", "3"] if user_id == "2" else [user_id]
                return json.dumps({
                    "users": [
                        {
                            "rank": 40 + int(selected_user_id),
                            "score": 100 - int(selected_user_id),
                            "percentage": 50,
                            "codingamer": {
                                "publicHandle": f"public-{selected_user_id}",
                                "userId": int(selected_user_id),
                                "pseudo": f"user-{selected_user_id}",
                            },
                        }
                        for selected_user_id in user_ids
                    ]
                    + [
                        {
                            "rank": 999,
                            "score": 1,
                            "codingamer": {
                                "publicHandle": "unselected",
                                "userId": 999,
                                "pseudo": "unselected",
                            },
                        },
                    ],
                    "programmingLanguages": {},
                })
            if url == "https://www.codingame.com/contests/test-challenge/leaderboard":
                return '<script src="https://static.codingame.com/app.codingame.test.js"></script>'
            if url == "https://static.codingame.com/app.codingame.test.js":
                return 'const t={EN:[{id:"US",name:"United States"},{id:"FR",name:"France"}],FR:'
            raise AssertionError(f"unexpected request: {url}")

        with mock.patch("ranking.management.modules.codingame.REQ.get", side_effect=get):
            standings = Statistic(contest=contest).get_standings(users=["1", "2", "3"], statistics={})

        account_set.filter.assert_called_once_with(key__in={"1", "2", "3"})
        assert leaderboard_requests == ["public-1", "public-2"]
        assert set(standings["result"]) == {"1", "2", "3"}
        assert standings["result"]["1"]["info"]["profile_url"] == {"public_handle": "public-1"}
        assert [standings["result"][user]["place"] for user in ("1", "2", "3")] == [41, 42, 43]
        assert all("rank" not in row["_score_percentage"] for row in standings["result"].values())
        assert "percentage" not in standings["fields_values"]
