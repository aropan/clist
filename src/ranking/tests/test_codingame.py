import json
import re
from datetime import timedelta
from math import isclose
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from django.utils.timezone import now

from notification.utils import CUSTOM_MESSAGE_PLACEHOLDERS
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


LEAGUE_INDEXES = {"legend": 0, "gold": 1, "silver": 2, "bronze": 3}


class CodingameProgressMessagesTest(SimpleTestCase):
    SCRIPT_JS = (
        'const t={EN:[{id:"US",name:"United States"},{id:"FR",name:"France"}],FR:[]};'
        'var l={"league":{"league":"league","legend":"legend league","gold":"gold league",'
        '"silver":"silver league","bronze":"bronze league","wood":"wood league"},"other":1}'
    )

    def make_contest(self, resource=None):
        current_time = now()
        return SimpleNamespace(
            pk=1,
            title="Test challenge",
            url="https://www.codingame.com/contests/test-challenge",
            key="test-challenge",
            standings_url=None,
            start_time=current_time - timedelta(days=2),
            end_time=current_time - timedelta(days=1),
            info={},
            resource=resource or SimpleNamespace(account_set=mock.Mock()),
            invisible=False,
        )

    def make_row(self, user_id=1, rank=10, score=20.0, percentage=100, agent_id=100, league="bronze"):
        row = {
            "rank": rank,
            "score": score,
            "agentId": agent_id,
            "localRank": rank,
            "codingamer": {"publicHandle": f"public-{user_id}", "userId": user_id, "pseudo": f"user-{user_id}"},
        }
        if percentage is not None:
            row["percentage"] = percentage
        if league is not None:
            row["league"] = {"divisionCount": 5, "divisionIndex": 5 - LEAGUE_INDEXES[league] - 1}
        return row

    def get_standings(self, rows, statistics=None, users=None, contest=None, script_js=None):
        contest = contest or self.make_contest()
        script_js = script_js or self.SCRIPT_JS

        def get(url, post=None, **kwargs):
            if url.endswith("services/Challenge/findWorldCupByPublicId"):
                return json.dumps({"challenge": {"type": "BATTLE"}})
            if url.endswith("services/Leaderboards/getFilteredChallengeLeaderboard"):
                return json.dumps({"users": rows, "programmingLanguages": {}})
            if url == "https://www.codingame.com/contests/test-challenge/leaderboard":
                return '<script src="https://static.codingame.com/app.codingame.test.js"></script>'
            if url == "https://static.codingame.com/app.codingame.test.js":
                return script_js
            raise AssertionError(f"unexpected request: {url}")

        with mock.patch("ranking.management.modules.codingame.REQ.get", side_effect=get):
            standings = Statistic(contest=contest).get_standings(users=users, statistics=statistics or {})
        return standings["result"]

    def test_leagues_are_resolved_from_script(self):
        result = self.get_standings([self.make_row(league="silver")])
        assert result["1"]["league"] == "Silver"

    def test_first_observation_initializes_progress_without_message(self):
        result = self.get_standings([self.make_row(rank=10)])
        row = result["1"]
        assert "_subscription_messages" not in row
        assert row["_agent_id"] == 100
        assert row["_league"] == "Bronze"
        assert row["_best_place"] == 10

    def test_row_saved_before_progress_fields_only_initializes(self):
        statistics = {"1": {"_agent_id": 99, "_score_history": []}}
        result = self.get_standings([self.make_row(rank=10, agent_id=100)], statistics=statistics)
        row = result["1"]
        assert "_subscription_messages" not in row
        assert row["_best_place"] == 10
        assert row["_league"] == "Bronze"

    def test_league_change_message(self):
        statistics = {"1": {"_agent_id": 100, "_league": "Bronze", "_best_place": 50, "_score_history": []}}
        result = self.get_standings([self.make_row(rank=30, agent_id=101, league="silver")], statistics=statistics)
        row = result["1"]
        (message,) = row["_subscription_messages"]
        assert message["type"] == "league_change"
        assert message["message"] == ("{account} moved to `Silver` league from `Bronze`, place `30`. {contest}")
        assert row["_best_place"] == 30
        assert row["_league"] == "Silver"

    def test_league_change_without_new_agent_still_notifies(self):
        statistics = {"1": {"_agent_id": 100, "_league": "Bronze", "_best_place": 50, "_score_history": []}}
        result = self.get_standings([self.make_row(rank=60, agent_id=100, league="silver")], statistics=statistics)
        row = result["1"]
        (message,) = row["_subscription_messages"]
        assert message["type"] == "league_change"
        assert row["_best_place"] == 60
        assert not row["_score_history"][-1].get("updated")

    def test_best_place_message(self):
        statistics = {"1": {"_agent_id": 100, "_league": "Bronze", "_best_place": 50, "_score_history": []}}
        result = self.get_standings([self.make_row(rank=30, agent_id=101)], statistics=statistics)
        row = result["1"]
        (message,) = row["_subscription_messages"]
        assert message["type"] == "best_place"
        assert message["message"] == ("{account} improved place `50` → `30` in `Bronze` league. {contest}")
        assert row["_best_place"] == 30
        assert row["_score_history"][-1]["updated"]

    def test_worse_place_keeps_best_place_and_sends_nothing(self):
        statistics = {"1": {"_agent_id": 100, "_league": "Bronze", "_best_place": 50, "_score_history": []}}
        result = self.get_standings([self.make_row(rank=60, agent_id=101)], statistics=statistics)
        row = result["1"]
        assert "_subscription_messages" not in row
        assert row["_best_place"] == 50

    def test_same_agent_and_league_is_not_an_event(self):
        statistics = {"1": {"_agent_id": 100, "_league": "Bronze", "_best_place": 50, "_score_history": []}}
        result = self.get_standings([self.make_row(rank=30, agent_id=100)], statistics=statistics)
        row = result["1"]
        assert "_subscription_messages" not in row
        assert row["_best_place"] == 50

    def test_league_change_has_priority_over_best_place(self):
        statistics = {"1": {"_agent_id": 100, "_league": "Bronze", "_best_place": 50, "_score_history": []}}
        result = self.get_standings([self.make_row(rank=30, agent_id=101, league="silver")], statistics=statistics)
        messages = result["1"]["_subscription_messages"]
        assert [message["type"] for message in messages] == ["league_change"]

    def test_unfinished_percentage_keeps_progress_fields(self):
        statistics = {"1": {"_agent_id": 100, "_league": "Bronze", "_best_place": 50, "_solving": 18.0}}
        result = self.get_standings(
            [self.make_row(rank=30, agent_id=101, percentage=50, score=25.0)],
            statistics=statistics,
        )
        row = result["1"]
        assert "_subscription_messages" not in row
        assert row["_agent_id"] == 100
        assert row["_best_place"] == 50
        assert row["_league"] == "Bronze"

    def test_messages_only_use_known_placeholders(self):
        statistics = {"1": {"_agent_id": 100, "_league": "Bronze", "_best_place": 50, "_score_history": []}}
        result = self.get_standings([self.make_row(rank=30, agent_id=101, league="silver")], statistics=statistics)
        for message in result["1"]["_subscription_messages"]:
            for name in re.findall(r"\{(\w+)\}", message["message"]):
                assert name in CUSTOM_MESSAGE_PLACEHOLDERS, name

    def test_partial_update_freezes_progress_and_history(self):
        account = SimpleNamespace(key="1", info={"profile_url": {"public_handle": "public-1"}})
        account_set = mock.Mock()
        account_set.filter.return_value = [account]
        contest = self.make_contest(resource=SimpleNamespace(account_set=account_set))
        history = [{"timestamp": 1, "score": 18.0, "rank": 50, "league": "Bronze"}]
        statistics = {
            "1": {
                "_agent_id": 100,
                "_league": "Bronze",
                "_best_place": 50,
                "_league_index": 3,
                "_solving": 18.0,
                "_score_history": [dict(point) for point in history],
            }
        }

        result = self.get_standings(
            [self.make_row(rank=30, agent_id=101, score=25.0)],
            statistics=statistics,
            users=["1"],
            contest=contest,
        )

        row = result["1"]
        assert "_subscription_messages" not in row
        assert row["_agent_id"] == 100
        assert row["_league"] == "Bronze"
        assert row["_best_place"] == 50
        assert row["_score_history"] == history
        assert isclose(row["_solving"], 25.0)

    def test_missing_league_does_not_notify_about_none_league(self):
        statistics = {"1": {"_agent_id": 100, "_league": "Bronze", "_best_place": 50, "_score_history": []}}

        result = self.get_standings(
            [self.make_row(rank=30, agent_id=101, league=None)],
            statistics=statistics,
        )

        row = result["1"]
        assert "_subscription_messages" not in row
        assert row["_league"] is None
        assert row["_best_place"] == 30

    def test_league_name_with_markdown_is_escaped(self):
        script_js = self.SCRIPT_JS.replace('"silver":"silver league"', '"silver":"silver_x league"')
        statistics = {"1": {"_agent_id": 100, "_league": "Bronze", "_best_place": 50, "_score_history": []}}

        result = self.get_standings(
            [self.make_row(rank=30, agent_id=101, league="silver")],
            statistics=statistics,
            script_js=script_js,
        )

        (message,) = result["1"]["_subscription_messages"]
        assert message["message"] == ("{account} moved to `Silver\\_X` league from `Bronze`, place `30`. {contest}")

    def test_contest_without_percentage_produces_no_messages(self):
        statistics = {"1": {"_agent_id": 100, "_league": "Bronze", "_best_place": 50, "_score_history": []}}

        result = self.get_standings(
            [self.make_row(rank=30, agent_id=101, percentage=None)],
            statistics=statistics,
        )

        row = result["1"]
        assert "_subscription_messages" not in row
        assert row["_agent_id"] == 100
        assert row["_best_place"] == 50

    def test_event_is_not_lost_after_partial_update(self):
        account = SimpleNamespace(key="1", info={"profile_url": {"public_handle": "public-1"}})
        account_set = mock.Mock()
        account_set.filter.return_value = [account]
        partial_contest = self.make_contest(resource=SimpleNamespace(account_set=account_set))
        statistics = {"1": {"_agent_id": 100, "_league": "Bronze", "_best_place": 50, "_score_history": []}}

        partial = self.get_standings(
            [self.make_row(rank=30, agent_id=101)],
            statistics=statistics,
            users=["1"],
            contest=partial_contest,
        )
        assert "_subscription_messages" not in partial["1"]

        carried = {"1": {key: partial["1"][key] for key in ("_agent_id", "_league", "_best_place", "_score_history")}}
        full = self.get_standings([self.make_row(rank=30, agent_id=101)], statistics=carried)

        (message,) = full["1"]["_subscription_messages"]
        assert message["type"] == "best_place"
