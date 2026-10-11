import re
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from clist.models import Contest, Resource
from clist.tests import MIDDLEWARE_WITHOUT_DEBUG_TOOLING
from ranking.enums import AccountType
from ranking.models import Account, Statistics
from ranking.views import (
    _get_standings_row,
    get_standings_account_type,
    get_standings_fields,
    render_standings_paging,
    versus,
)


class VersusTest(SimpleTestCase):
    def test_invalid_remove_index_is_rejected(self):
        request = RequestFactory().get("/versus/", {"remove": "not-an-integer"})
        response = versus(request, "first/vs/second")
        assert response.status_code == 400


class StandingsVersusColumnsTemplateTest(SimpleTestCase):
    def test_renders_table_cells_without_tag_context(self):
        content = render_to_string(
            "standings_versus_columns.html",
            {
                "versus_data": {"fields": []},
                "versus_data_row": {"win": 1, "lose": 0, "draw": 0, "total": 1},
            },
        )

        assert '<td class="versus-cell">' in content
        assert content.count("<td") == 3
        assert "<>" not in content


@override_settings(MIDDLEWARE=MIDDLEWARE_WITHOUT_DEBUG_TOOLING)
class VersusRatingTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.resource = Resource.objects.create(
            host="versus-rating.example.com",
            enable=True,
            url="https://versus-rating.example.com/",
            has_rating_history=True,
            color="#336699",
            icon_file="resources/test.png",
            icon_updated_at=now,
        )
        cls.contest = Contest.objects.create(
            resource=cls.resource,
            title="Versus rating",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            duration_in_secs=3600,
            url="https://versus-rating.example.com/contest",
            key="versus-rating",
            host=cls.resource.host,
            parsed_time=now,
            is_rated=True,
        )
        cls.accounts = [Account.objects.create(resource=cls.resource, key=key) for key in ("first", "second")]
        for place, account in enumerate(cls.accounts, start=1):
            Statistics.objects.create(
                account=account,
                contest=cls.contest,
                resource=cls.resource,
                place=str(place),
                place_as_int=place,
                solving=3 - place,
                addition={"old_rating": 1500, "rating_change": place * 10, "new_rating": 1500 + place * 10},
            )

    def test_different_accounts_share_resource_rating_chart(self):
        query = "/vs/".join(f"{self.resource.host}:{account.key}" for account in self.accounts)

        response = self.client.get(reverse("ranking:versus", args=[query]))

        assert response.status_code == 200
        ratings = response.context["versus_data"]["ratings"]
        assert set(ratings["resources"]) == {self.resource.host}
        assert len(ratings["resources"][self.resource.host]["data"]) == 2
        assert response.content.count(b'class="rating_history"') == 1


class StandingsFieldsTest(SimpleTestCase):
    @staticmethod
    def create_contest(default_account_type=AccountType.USER, with_account_type=True):
        resource = Resource(info={}, default_account_type=default_account_type)
        return Contest(
            resource=resource,
            info={
                "fields": ["n_gold"],
                "standings": {
                    "with_account_type": with_account_type,
                    "account_type_fields": {"member": {"fixed_fields": ["n_gold"]}},
                },
            },
        )

    def test_member_account_type_scopes_its_fixed_fields(self):
        contest = self.create_contest()

        for with_detail in (False, True):
            with self.subTest(with_detail=with_detail):
                member_fields = get_standings_fields(
                    contest, division=None, with_detail=with_detail, account_type="member"
                )
                user_fields = get_standings_fields(contest, division=None, with_detail=with_detail, account_type="user")

                assert "n_gold" in member_fields
                assert "n_gold" not in user_fields

    def test_account_type_is_normalized(self):
        contest = self.create_contest()

        for value in ("member", "MEMBER"):
            with self.subTest(value=value):
                account_type, account_type_value = get_standings_account_type(contest, value)
                assert account_type == AccountType.MEMBER
                assert account_type_value == "member"

    def test_default_account_type_is_used(self):
        contest = self.create_contest(default_account_type=AccountType.MEMBER)

        account_type, account_type_value = get_standings_account_type(contest, None)

        assert account_type == AccountType.MEMBER
        assert account_type_value == "member"

    def test_account_type_is_ignored_when_filter_is_disabled(self):
        contest = self.create_contest(with_account_type=False)

        assert get_standings_account_type(contest, "member") == (None, None)

    def test_saved_rating_prediction_does_not_duplicate_rating_fields(self):
        contest = self.create_contest()
        contest.resource.rating_prediction = {}
        contest.has_fixed_rating_prediction_field = True
        contest.rating_prediction_hash = "hash"
        contest.info["fields"].extend(["old_rating", "new_rating", "rating_change", "rating_perf"])
        contest.info["_rating_calculation"] = {"config": {"save_rating": True}}

        fields = get_standings_fields(contest, division=None, with_detail=True, account_type="member")

        assert "new_rating" in fields
        assert "rating_perf" in fields
        assert "predicted_new_rating" not in fields
        assert "predicted_rating_perf" not in fields

        contest.info["_rating_calculation"]["config"]["save_rating"] = False
        fields = get_standings_fields(contest, division=None, with_detail=True, account_type="member")

        assert "predicted_new_rating" in fields
        assert "predicted_rating_perf" in fields

    def test_rating_prediction_fields_are_scoped_to_configured_account_type(self):
        contest = self.create_contest()
        contest.resource.rating_prediction = {}
        contest.has_fixed_rating_prediction_field = True
        contest.rating_prediction_hash = "hash"
        contest.info["_rating_calculation"] = {"config": {"account_type": "member", "save_rating": False}}

        member_fields = get_standings_fields(contest, division=None, with_detail=True, account_type="member")
        user_fields = get_standings_fields(contest, division=None, with_detail=True, account_type="user")

        assert "predicted_new_rating" in member_fields
        assert "predicted_rating_perf" in member_fields
        assert "predicted_new_rating" not in user_fields
        assert "predicted_rating_perf" not in user_fields


@override_settings(MIDDLEWARE=MIDDLEWARE_WITHOUT_DEBUG_TOOLING)
class MixedTeamStandingsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.resource = Resource.objects.create(
            host="mixed-teams.example.com",
            enable=True,
            url="https://mixed-teams.example.com/",
            color="#336699",
            icon_file="resources/test.png",
            icon_updated_at=now,
        )
        cls.contest = Contest.objects.create(
            resource=cls.resource,
            title="Mixed team standings",
            key="mixed-teams",
            url="https://mixed-teams.example.com/contest",
            host=cls.resource.host,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            duration_in_secs=3600,
            parsed_time=now,
            n_statistics=4,
            info={"fields": ["team_id", "name", "penalty"], "grouped_team": True},
        )
        cls.statistics = {}
        for handle, team_id in (
            ("alice", None),
            ("bob", None),
            ("carol", "first"),
            ("dave", "first"),
            ("eve", "second"),
        ):
            account = Account.objects.create(resource=cls.resource, key=handle)
            addition = {"team_id": team_id, "name": team_id} if team_id else {}
            statistic = Statistics.objects.create(
                contest=cls.contest,
                resource=cls.resource,
                account=account,
                place="1",
                place_as_int=1,
                solving=100,
                penalty=0,
                addition=addition,
            )
            cls.statistics[handle] = statistic
            if handle == "bob":
                cls.bob = statistic

    def assert_rendered_rows(self, **params):
        response = self.client.get(reverse("ranking:standings_by_id", args=[self.contest.pk]), params)
        assert response.status_code == 200
        statistic_ids = re.findall(rb'data-statistic-id="([0-9]+)"', response.content)
        assert len(statistic_ids) == 4
        statistics = Statistics.objects.filter(pk__in=[int(pk) for pk in statistic_ids])
        assert set(statistics.filter(addition__team_id__isnull=True).values_list("account__key", flat=True)) == {
            "alice",
            "bob",
        }
        assert statistics.filter(addition__team_id="first").count() == 1
        assert statistics.filter(addition__team_id="second").count() == 1

    def test_small_mixed_standings_keep_tied_individuals_and_group_team_members(self):
        self.contest.info["grouped_team"] = False
        self.contest.save(update_fields=["info"])
        self.assert_rendered_rows()

    @override_settings(STANDINGS_SMALL_N_STATISTICS=0)
    def test_forced_grouping_keeps_tied_individuals_and_supports_find_me(self):
        self.assert_rendered_rows(find_me=self.bob.pk)

    def test_search_finds_any_team_member(self):
        for handle in ("carol", "dave"):
            with self.subTest(handle=handle):
                response = self.client.get(
                    reverse("ranking:standings_by_id", args=[self.contest.pk]), {"search": handle}
                )
                assert response.status_code == 200
                statistic_ids = re.findall(rb'data-statistic-id="([0-9]+)"', response.content)
                assert len(statistic_ids) == 1
                assert Statistics.objects.get(pk=int(statistic_ids[0])).account.key == handle

    def test_find_me_paginates_by_grouped_rows(self):
        with mock.patch.object(Contest, "standings_per_page", new_callable=mock.PropertyMock, return_value=2):
            response = self.client.get(
                reverse("ranking:standings_by_id", args=[self.contest.pk]), {"find_me": self.bob.pk}
            )

        assert response.status_code == 200
        assert int(response.wsgi_request.GET["standings_paging"]) == 2
        assert re.findall(rb'data-statistic-id="([0-9]+)"', response.content) == [
            str(self.statistics["alice"].pk).encode(),
            str(self.bob.pk).encode(),
        ]
        assert re.findall(rb'<tr\b[^>]*\bfind-me-row\b[^>]*data-statistic-id="([0-9]+)"', response.content) == [
            str(self.bob.pk).encode()
        ]

    def test_find_me_highlights_team_for_nonrepresentative_member(self):
        Statistics.objects.filter(contest=self.contest, addition__team_id="first").update(place="2", place_as_int=2)
        with mock.patch.object(Contest, "standings_per_page", new_callable=mock.PropertyMock, return_value=2):
            response = self.client.get(
                reverse("ranking:standings_by_id", args=[self.contest.pk]),
                {"find_me": self.statistics["dave"].pk},
            )

        assert response.status_code == 200
        assert int(response.wsgi_request.GET["standings_paging"]) == 2
        assert response.context["find_me"] == self.statistics["carol"].pk
        assert re.findall(rb'<tr\b[^>]*\bfind-me-row\b[^>]*data-statistic-id="([0-9]+)"', response.content) == [
            str(self.statistics["carol"].pk).encode()
        ]

    def test_charts_find_me_highlights_any_team_member_and_individual(self):
        Statistics.objects.filter(contest=self.contest, addition__team_id="first").update(solving=200)
        for handle, representative, score in (("carol", "carol", 200), ("dave", "carol", 200), ("alice", "alice", 100)):
            with self.subTest(handle=handle):
                response = self.client.get(
                    reverse("ranking:standings_by_id", args=[self.contest.pk]),
                    {"charts": "yes", "find_me": self.statistics[handle].pk},
                )

                assert response.status_code == 200
                assert response.context["find_me"] == self.statistics[representative].pk
                scores_chart = next(chart for chart in response.context["charts"] if chart["field"] == "scores")
                assert scores_chart["my_value"] == score

    def test_grouped_find_me_uses_one_query_without_loading_account_payloads(self):
        response = self.client.get(reverse("ranking:standings_by_id", args=[self.contest.pk]))
        statistics = response.context["groupby_data"]

        with CaptureQueriesContext(connection) as queries:
            row = _get_standings_row(statistics, list(statistics.query.order_by), self.statistics["dave"].pk)

        assert row == {"pk": self.statistics["carol"].pk, "place_as_int": 1, "row_number": 1}
        assert len(queries) == 1
        sql = queries[0]["sql"]
        assert 'JOIN "ranking_account"' not in sql
        assert 'JOIN "clist_resource"' not in sql
        assert '"ranking_statistics"."addition" AS "addition"' not in sql

    def test_grouped_find_me_respects_search_filter(self):
        response = self.client.get(reverse("ranking:standings_by_id", args=[self.contest.pk]), {"search": "alice"})
        statistics = response.context["groupby_data"]

        assert _get_standings_row(statistics, list(statistics.query.order_by), self.statistics["dave"].pk) is None


class StandingsRowTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.resource = Resource.objects.create(
            host="standings-row.example.com",
            enable=True,
            url="https://standings-row.example.com/",
            color="#336699",
            icon_file="resources/test.png",
            icon_updated_at=now,
        )
        cls.contest = Contest.objects.create(
            resource=cls.resource,
            title="Standings row",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            duration_in_secs=3600,
            url="https://standings-row.example.com/contest",
            key="standings-row",
            host=cls.resource.host,
            parsed_time=now,
        )
        statistics = []
        for key, place, solving, penalty in (
            ("alice", 1, 100, 20),
            ("bob", 1, 100, 10),
            ("carol", 2, 90, 0),
        ):
            account = Account.objects.create(
                resource=cls.resource,
                key=key,
                info={"payload": "x" * 4096},
            )
            statistics.append(
                Statistics.objects.create(
                    account=account,
                    contest=cls.contest,
                    resource=cls.resource,
                    place_as_int=place,
                    solving=solving,
                    penalty=penalty,
                    addition={"payload": "x" * 4096},
                )
            )
        cls.alice, cls.bob, cls.carol = statistics

    def test_get_standings_row_sorts_only_required_columns(self):
        order = ["place_as_int", "-solving", "penalty", "pk"]
        statistics = (
            Statistics.objects
            .filter(contest=self.contest)
            .select_related("account__resource")
            .prefetch_related("account__coders")
            .order_by(*order)
        )

        with CaptureQueriesContext(connection) as queries:
            row = _get_standings_row(statistics, order, self.alice.pk)

        assert row == {"pk": self.alice.pk, "place_as_int": 1, "row_number": 2}
        assert len(queries) == 1
        sql = queries[0]["sql"]
        assert '"ranking_statistics"."addition"' not in sql
        assert 'JOIN "ranking_account"' not in sql
        assert 'JOIN "clist_resource"' not in sql

    def test_get_standings_row_returns_none_for_filtered_out_statistic(self):
        order = ["place_as_int", "-solving", "penalty", "pk"]
        statistics = Statistics.objects.filter(contest=self.contest, place_as_int=1).order_by(*order)

        assert _get_standings_row(statistics, order, self.carol.pk) is None

    def test_get_standings_row_uses_queryset_database(self):
        order = ["place_as_int", "-solving", "penalty", "pk"]
        statistics = Statistics.objects.filter(contest=self.contest).order_by(*order)

        raw_row = mock.Mock(pk=self.alice.pk, place_as_int=1, row_number=1)
        with mock.patch.object(Statistics.objects, "raw", return_value=[raw_row]) as raw:
            row = _get_standings_row(statistics, order, self.alice.pk)

        assert raw.call_args.kwargs["using"] == statistics.db
        assert row == {"pk": self.alice.pk, "place_as_int": 1, "row_number": 1}

    @mock.patch("ranking.views.get_template")
    def test_live_render_uses_full_small_contest_page_size(self, get_template):
        self.contest.n_statistics = 163
        statistic_ids = [self.alice.pk, self.bob.pk, self.carol.pk]
        get_template.return_value.render.side_effect = lambda context: str(context["per_page"])

        rendered = render_standings_paging(self.contest, statistic_ids, with_detail=False)

        assert rendered == {"page": "163", "total": 3}

    def test_live_render_escapes_parser_markup(self):
        attack = '<img src=x onerror="alert(1)">'
        self.contest.info = {"problems": [{"short": "A", "full_score": 100}]}
        self.contest.save(update_fields=["info"])
        self.alice.account.url = "javascript:alert(1)"
        self.alice.account.save(update_fields=["url"])
        self.alice.addition = {"url": "javascript:alert(1)", "problems": {"A": {"result": attack, "icon": attack}}}
        self.alice.save(update_fields=["addition"])

        page = render_standings_paging(self.contest, [self.alice.pk], with_detail=False)["page"]

        assert attack not in page
        assert "&lt;img" in page
        assert 'href="javascript:' not in page
