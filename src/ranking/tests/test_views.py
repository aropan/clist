from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from clist.models import Contest, Resource
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

    def test_member_account_type_adds_its_fixed_fields(self):
        contest = self.create_contest()

        member_fields = get_standings_fields(contest, division=None, with_detail=False, account_type="member")
        user_fields = get_standings_fields(contest, division=None, with_detail=False, account_type="user")

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

        assert row == {"place_as_int": 1, "row_number": 2}
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

        raw_row = mock.Mock(place_as_int=1, row_number=1)
        with mock.patch.object(Statistics.objects, "raw", return_value=[raw_row]) as raw:
            row = _get_standings_row(statistics, order, self.alice.pk)

        assert raw.call_args.kwargs["using"] == statistics.db
        assert row == {"place_as_int": 1, "row_number": 1}

    @mock.patch("ranking.views.get_template")
    def test_live_render_uses_full_small_contest_page_size(self, get_template):
        self.contest.n_statistics = 163
        statistic_ids = [self.alice.pk, self.bob.pk, self.carol.pk]
        get_template.return_value.render.side_effect = lambda context: str(context["per_page"])

        rendered = render_standings_paging(self.contest, statistic_ids, with_detail=False)

        assert rendered == {"page": "163", "total": 3}
