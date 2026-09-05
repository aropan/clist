import math
from collections import OrderedDict
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from clist.models import Contest, Resource
from ranking.management.modules.common import apply_result_additions
from ranking.management.modules.stats_ioinformatics import (
    REQ,
    Statistic,
    get_member_results,
    get_official_ranking_base_url,
    parse_delegation,
)


class OfficialRankingUrlTest(SimpleTestCase):
    def test_explicit_ranking_url_takes_precedence(self):
        info = {
            "_official_website_ranking": "https://ranking.ioi2025.bo",
            "parse": {"website": "https://ioi2025.obi.org.bo"},
        }

        assert get_official_ranking_base_url(info) == "https://ranking.ioi2025.bo"

    def test_ranking_url_is_derived_when_override_is_missing(self):
        info = {"parse": {"website": "https://ioi2024.eg/path//kept"}}

        assert get_official_ranking_base_url(info) == "https://ranking.ioi2024.eg/path//kept"

    def test_missing_website_disables_ranking_enrichment(self):
        assert get_official_ranking_base_url({}) is None


class DelegationTest(SimpleTestCase):
    def test_empty_member_cell_has_no_delegation(self):
        assert parse_delegation("", []) == {}

    def test_member_link_and_country_are_parsed(self):
        assert parse_delegation("China 4", ["/members/CHN"]) == {
            "delegation": "CHN",
            "country": "China",
        }


class StandingsAdditionsTest(SimpleTestCase):
    def test_delegations_use_overrides_without_renaming_source_rows(self):
        contest = Contest(
            resource=Resource(),
            url="https://stats.ioinformatics.org/olympiads/2024",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            info={
                "additions": {
                    "Original Name": {
                        "name": "Corrected Name",
                        "delegation": "USA",
                        "country": "United States",
                        "solving": 50,
                        "medal": "silver",
                    }
                }
            },
        )
        page = """
            <table>
                <tr><th>Rank</th><th>Contestant</th><th>Country</th><th>Abs.</th><th>Medal</th></tr>
                <tr>
                    <td>1</td><td><a href="/people/person-1">Original Name</a></td>
                    <td><a href="/members/CHN">China</a></td><td>100</td><td>Gold</td>
                </tr>
            </table>
        """

        with mock.patch.object(REQ, "get", side_effect=["", page, ""]):
            standings = Statistic(contest=contest).get_standings()

        result = standings["result"]
        assert result["person-1"]["name"] == "Original Name"
        assert result["person-1"]["solving"] == 100
        assert "CHN" not in result
        assert result["USA"]["solving"] == 50
        assert result["USA"]["n_silver"] == 1

        apply_result_additions(contest, result, add_missing=True)

        assert set(result) == {"person-1", "USA"}
        assert result["person-1"]["name"] == "Corrected Name"
        assert result["person-1"]["solving"] == 50


class MemberResultsTest(SimpleTestCase):
    def test_aggregates_ranked_contestants_and_assigns_competition_places(self):
        result = OrderedDict([
            (
                "person-1",
                {
                    "member": "person-1",
                    "delegation": "CHN",
                    "country": "China",
                    "solving": 100,
                    "medal": "gold",
                    "problems": {"A": {"result": 100, "partial": False}},
                },
            ),
            (
                "person-2",
                {
                    "member": "person-2",
                    "delegation": "CHN",
                    "country": "China",
                    "solving": 50,
                    "medal": "silver",
                    "problems": {
                        "A": {"result": 50, "partial": True},
                        "B": {"result": 100, "partial": False},
                    },
                },
            ),
            (
                "observer",
                {
                    "member": "observer",
                    "delegation": "CHN",
                    "country": "China",
                    "solving": 999,
                    "medal": "bronze",
                    "problems": {},
                    "_no_update_n_contests": True,
                },
            ),
            (
                "person-3",
                {
                    "member": "person-3",
                    "delegation": "USA",
                    "country": "United States of America",
                    "solving": 150,
                    "medal": "gold",
                    "problems": {"B": {"result": 100, "partial": False}},
                },
            ),
        ])
        hidden_fields = {}

        member_result, member_fields = get_member_results(result, hidden_fields)

        assert list(member_result) == ["CHN", "USA"]
        assert member_result["CHN"] == {
            "member": "CHN",
            "name": "China",
            "place": 1,
            "solving": 150,
            "n_gold": 1,
            "n_silver": 1,
            "problems": {
                "A": {"result": 150, "partial": True},
                "B": {"result": 100, "partial": True},
            },
            "info": {"profile_url": {"type": "members"}, "is_member": True},
            "_skip_for_problem_stat": True,
            "_skip_for_n_statistics": True,
            "_skip_subscription": True,
        }
        assert member_result["USA"]["place"] == 1
        assert member_result["USA"]["problems"] == {"B": {"result": 100, "partial": False}}
        assert member_fields == ["n_gold", "n_silver"]
        assert hidden_fields == {"n_gold": True, "n_silver": True}

    def test_rounds_scores_before_comparing_ties(self):
        result = {
            "person-1": {"delegation": "AAA", "solving": 0.1, "problems": {"A": {"result": 0.1}}},
            "person-2": {"delegation": "AAA", "solving": 0.2, "problems": {"A": {"result": 0.2}}},
            "person-3": {"delegation": "BBB", "solving": 0.3, "problems": {"A": {"result": 0.3}}},
        }

        member_result, _ = get_member_results(result, {}, score_precision=2)

        assert math.isclose(member_result["AAA"]["solving"], 0.3)
        assert math.isclose(member_result["AAA"]["problems"]["A"]["result"], 0.3)
        assert member_result["AAA"]["place"] == member_result["BBB"]["place"] == 1


class MemberUsersInfoTest(SimpleTestCase):
    @staticmethod
    def get_account():
        account = mock.Mock()
        account.info = {"is_member": True}
        account.dict_with_info.return_value = {"type": "members", "account": "CHN"}
        return account

    def test_parses_member_profile(self):
        page = """
            <div class="countryname"><div>China</div></div>
            <img class="countryflag" src="/img/flags/CHN.png">
            <li>Gold medals: 109</li>
            <li>Years participated: 38</li>
        """
        resource = SimpleNamespace(profile_url="https://stats.ioinformatics.org/{type}/{account}")

        with mock.patch.object(REQ, "get", return_value=page):
            infos = list(Statistic.get_users_infos(["CHN"], resource, [self.get_account()]))

        assert infos == [
            {
                "info": {
                    "name": "China",
                    "avatar_url": "https://stats.ioinformatics.org/img/flags/CHN.png",
                    "gold_medals": 109,
                    "years_participated": 38,
                }
            }
        ]

    def test_missing_member_name_does_not_fail(self):
        page = "<li>Years participated: 38</li>"
        resource = SimpleNamespace(profile_url="https://stats.ioinformatics.org/{type}/{account}")

        with mock.patch.object(REQ, "get", return_value=page):
            infos = list(Statistic.get_users_infos(["CHN"], resource, [self.get_account()]))

        assert infos == [{"info": {"years_participated": 38}}]
