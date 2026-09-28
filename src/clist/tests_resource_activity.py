import json
import math
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest import mock

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from clist.models import Contest, ContestSeries, Resource
from clist.resource_activity import calculate_activity_scores, get_resource_activity_scores
from clist.views import resources
from ranking.models import Account
from true_coders.models import Coder
from true_coders.views import search

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)


def contest_data(contest_id=1, resource_id=1, **overrides):
    data = {
        "id": contest_id,
        "resource_id": resource_id,
        "start_time": NOW - timedelta(days=1, hours=2),
        "end_time": NOW - timedelta(days=1),
        "n_statistics": None,
        "is_promoted": None,
        "is_rated": None,
        "series_id": None,
    }
    data.update(overrides)
    return data


class ActivityFormulaTest(SimpleTestCase):
    def score(self, contests, linked_ids=None, major_series_ids=None, active_coders=None, now=NOW):
        return calculate_activity_scores(
            contests,
            linked_ids or set(),
            major_series_ids or set(),
            active_coders or {},
            now,
        )

    def test_series_inherits_major_status_and_bonus(self):
        final = contest_data(series_id=7)
        ordinary = self.score([final])[1]
        major = self.score([final], major_series_ids={7})[1]
        assert major > ordinary
        assert self.score([final], linked_ids={1})[1] == major

        without_series = contest_data(series_id=None)
        major_without_bonus = self.score([without_series], linked_ids={1})[1]
        assert major > major_without_bonus

        older_final = contest_data(
            series_id=7,
            start_time=NOW - timedelta(days=181, hours=2),
            end_time=NOW - timedelta(days=181),
        )
        assert self.score([older_final], major_series_ids={7})[1] < major

    def test_monthly_volume_has_logarithmic_addition(self):
        first = contest_data()
        second = contest_data(contest_id=2, end_time=NOW - timedelta(days=2))
        single = self.score([first])[1]
        both = self.score([first, second])[1]
        q1 = 2 ** (-1 / 120)
        q2 = 2 ** (-2 / 120)
        expected_raw = q1 + 0.25 * math.log1p(q1 + q2)
        expected = -100 * math.expm1(-expected_raw / 20)
        assert both > single
        assert math.isclose(both, expected)

    def test_upcoming_contest_is_halved_and_old_contest_decays(self):
        recent = contest_data(is_rated=True, start_time=NOW - timedelta(hours=2), end_time=NOW)
        upcoming = contest_data(
            is_rated=True,
            start_time=NOW + timedelta(days=2),
            end_time=NOW + timedelta(days=2, hours=2),
        )
        old = contest_data(
            is_rated=True,
            start_time=NOW - timedelta(days=180, hours=2),
            end_time=NOW - timedelta(days=180),
        )
        recent_score = self.score([recent])[1]
        upcoming_score = self.score([upcoming])[1]
        old_score = self.score([old])[1]
        assert recent_score > upcoming_score
        assert recent_score > old_score
        assert math.isclose(upcoming_score, old_score)

    def test_missing_statistics_and_medals_do_not_change_score(self):
        without_medals = contest_data(n_statistics=None, with_medals=False)
        with_medals = contest_data(n_statistics=0, with_medals=True)
        assert self.score([without_medals]) == self.score([with_medals])

    def test_usage_is_capped_and_does_not_revive_empty_resource(self):
        contest = contest_data()
        no_links = self.score([contest])[1]
        many_links = self.score([contest], active_coders={1: 100000})[1]
        capped_links = self.score([contest], active_coders={1: 5000})[1]
        assert many_links == capped_links
        assert many_links > no_links
        assert self.score([], active_coders={1: 5000}) == {}


class ActivityQueryTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        patcher = mock.patch.object(Resource, "update_icon")
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        cls.resource = Resource.objects.create(host="activity.example", enable=True, url="https://activity.example/")
        cls.other = Resource.objects.create(
            host="activity-other.example", enable=True, url="https://activity-other.example/"
        )
        cls.cphof = Resource.objects.create(host="cphof.org", enable=True, url="https://cphof.org/")

    def create_contest(self, resource, key, end_time, **kwargs):
        return Contest.objects.create(
            resource=resource,
            title=key,
            start_time=end_time - timedelta(hours=2),
            end_time=end_time,
            url=f"https://{resource.host}/{key}",
            key=key,
            host=resource.host,
            **kwargs,
        )

    def test_cphof_series_history_promotes_unlinked_edition(self):
        series = ContestSeries.objects.create(name="Activity Annual Final", short="Activity Final")
        linked_ids = set()
        for year in (1, 2):
            final = self.create_contest(self.resource, f"old-{year}", NOW - timedelta(days=year * 365), series=series)
            self.create_contest(self.cphof, f"mirror-{year}", final.end_time, related=final)
            linked_ids.add(final.pk)
        latest = self.create_contest(self.resource, "latest", NOW - timedelta(days=1), series=series)
        scores = get_resource_activity_scores(NOW)
        contests = list(
            Contest.objects.filter(resource=self.resource).values(
                "id", "resource_id", "start_time", "end_time", "n_statistics", "is_promoted", "is_rated", "series_id"
            )
        )
        assert latest.pk not in linked_ids
        inherited = calculate_activity_scores(contests, linked_ids, {series.pk}, {}, NOW)[self.resource.pk]
        without_inheritance = calculate_activity_scores(contests, linked_ids, set(), {}, NOW)[self.resource.pk]
        assert math.isclose(scores[self.resource.pk], inherited)
        assert inherited > without_inheritance

    def test_active_linked_coder_is_distinct_and_queries_are_grouped(self):
        self.create_contest(self.resource, "contest", NOW - timedelta(days=1))
        self.create_contest(self.other, "other", NOW - timedelta(days=1))
        user = get_user_model().objects.create_user(username="activity-user")
        active = Coder.objects.create(user=user, username="activity-user", last_activity=NOW)
        virtual_user = get_user_model().objects.create_user(username="virtual-activity")
        virtual = Coder.objects.create(
            user=virtual_user, username="virtual-activity", is_virtual=True, last_activity=NOW
        )
        inactive_user = get_user_model().objects.create_user(username="inactive-activity")
        inactive = Coder.objects.create(
            user=inactive_user, username="inactive-activity", last_activity=NOW - timedelta(days=500)
        )
        userless = Coder.objects.create(username="userless-activity", last_activity=NOW)
        for key in ("one", "two"):
            account = Account.objects.create(resource=self.resource, key=key)
            account.coders.add(active, virtual, inactive, userless)

        with CaptureQueriesContext(connection) as queries:
            scores = get_resource_activity_scores(NOW)
        assert len(queries) <= 6
        expected = calculate_activity_scores(
            [contest_data(resource_id=self.resource.pk)],
            set(),
            set(),
            {self.resource.pk: 1},
            NOW,
        )[self.resource.pk]
        assert math.isclose(scores[self.resource.pk], expected)
        assert scores[self.resource.pk] > scores[self.other.pk]

        Resource.objects.create(host="activity-third.example", enable=True, url="https://activity-third.example/")
        with CaptureQueriesContext(connection) as more_queries:
            get_resource_activity_scores(NOW)
        assert len(queries) == len(more_queries)

    def test_contest_read_excludes_old_distant_and_invisible_events(self):
        eligible = self.create_contest(self.resource, "eligible", NOW - timedelta(days=1))
        self.create_contest(self.resource, "old", NOW - timedelta(days=1096))
        self.create_contest(self.resource, "future", NOW + timedelta(days=32))
        self.create_contest(self.resource, "hidden", NOW - timedelta(days=1), invisible=True)

        actual = get_resource_activity_scores(NOW)[self.resource.pk]
        expected = calculate_activity_scores(
            [
                {
                    "id": eligible.pk,
                    "resource_id": eligible.resource_id,
                    "start_time": eligible.start_time,
                    "end_time": eligible.end_time,
                    "n_statistics": eligible.n_statistics,
                    "is_promoted": eligible.is_promoted,
                    "is_rated": eligible.is_rated,
                    "series_id": eligible.series_id,
                }
            ],
            set(),
            set(),
            {},
            NOW,
        )[self.resource.pk]
        assert math.isclose(actual, expected)


class ActivityCommandTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        patcher = mock.patch.object(Resource, "update_icon")
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        cls.active = Resource.objects.create(
            host="active-command.example", enable=True, url="https://active-command.example/"
        )
        cls.empty = Resource.objects.create(
            host="empty-command.example", enable=True, url="https://empty-command.example/"
        )
        Contest.objects.create(
            resource=cls.active,
            title="Recent final",
            start_time=NOW - timedelta(days=1, hours=2),
            end_time=NOW - timedelta(days=1),
            url="https://active-command.example/final",
            key="final",
            host=cls.active.host,
        )

    def test_command_publishes_scores_and_can_be_rerun(self):
        with mock.patch("clist.management.commands.update_resource_activity.timezone.now", return_value=NOW):
            call_command("update_resource_activity", stdout=StringIO())
            self.active.refresh_from_db()
            self.empty.refresh_from_db()
            first_score = self.active.activity_score
            assert first_score > 0
            assert self.empty.activity_score == 0
            assert self.active.activity_updated_at == self.empty.activity_updated_at == NOW

            call_command("update_resource_activity", stdout=StringIO())
            self.active.refresh_from_db()
            assert self.active.activity_score == first_score
            assert self.active.activity_updated_at == NOW

    def test_failed_publication_rolls_back_all_scores(self):
        previous = NOW - timedelta(days=1)
        Resource.objects.update(activity_score=42, activity_updated_at=previous)

        def fail_after_write(objects, fields, batch_size):
            Resource.objects.filter(pk=objects[0].pk).update(activity_score=99, activity_updated_at=NOW)
            raise RuntimeError("publication failed")

        with (
            mock.patch(
                "clist.management.commands.update_resource_activity.get_resource_activity_scores", return_value={}
            ),
            mock.patch.object(Resource.objects, "bulk_update", side_effect=fail_after_write),
            pytest.raises(RuntimeError, match="publication failed"),
        ):
            call_command("update_resource_activity", stdout=StringIO())

        for resource in Resource.objects.all():
            assert resource.activity_score == 42
            assert resource.activity_updated_at == previous


class ActivityPageTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        patcher = mock.patch.object(Resource, "update_icon")
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        cls.high_priority = Resource.objects.create(
            host="page-priority.example",
            enable=True,
            url="https://page-priority.example/",
            n_contests=100,
            n_accounts=1000,
            activity_score=0,
            activity_updated_at=NOW,
        )
        cls.high_activity = Resource.objects.create(
            host="page-activity.example",
            enable=True,
            url="https://page-activity.example/",
            activity_score=90.234,
            activity_updated_at=NOW,
        )
        cls.tied_activity = Resource.objects.create(
            host="page-tied.example",
            enable=True,
            url="https://page-tied.example/",
            n_contests=2,
            activity_score=90.234,
            activity_updated_at=NOW,
        )
        cls.low_activity = Resource.objects.create(
            host="page-low.example",
            enable=True,
            url="https://page-low.example/",
            activity_score=10,
            activity_updated_at=NOW,
        )
        cls.uncalculated = Resource.objects.create(
            host="page-uncalculated.example", enable=True, url="https://page-uncalculated.example/"
        )

    def request(self):
        request = RequestFactory().get("/resources/")
        request.user = AnonymousUser()
        request.user_agent = mock.Mock(is_mobile=False)
        request.user_agent.browser.family = "Chrome"
        request.as_coder = None
        request.session = {}
        return request

    def test_page_orders_by_activity_and_ties_by_host(self):
        with mock.patch(
            "clist.views.render", side_effect=lambda _request, _template, context: list(context["resources"])
        ):
            ordered = resources(self.request())
        assert [resource.host for resource in ordered] == [
            "page-activity.example",
            "page-tied.example",
            "page-low.example",
            "page-priority.example",
            "page-uncalculated.example",
        ]
        queryset = Resource.priority_objects.all()
        assert [resource.host for resource in ordered] == list(queryset.values_list("host", flat=True))
        assert not {"priority", "rval", "pval"} & queryset.query.annotations.keys()

    def test_null_scores_order_by_host(self):
        Resource.objects.update(activity_score=None, activity_updated_at=None)
        with mock.patch(
            "clist.views.render", side_effect=lambda _request, _template, context: list(context["resources"])
        ):
            ordered = resources(self.request())
        assert [resource.host for resource in ordered] == list(
            Resource.objects.order_by("host").values_list("host", flat=True)
        )

    def search_hosts(self, **params):
        request = RequestFactory().get("/settings/search/", {"query": "resources", **params})
        request.user = AnonymousUser()
        return [resource["host"] for resource in json.loads(search(request).content)["items"]]

    def test_resource_search_uses_activity_order_and_stable_pagination(self):
        expected = list(Resource.priority_objects.values_list("host", flat=True))
        assert self.search_hosts() == expected
        assert self.search_hosts(count=2, page=2) == expected[2:4]

    def test_resource_search_keeps_exact_short_host_first(self):
        self.low_activity.short_host = "page"
        self.low_activity.save(update_fields=["short_host"])
        assert self.search_hosts(text="page") == [
            "page-low.example",
            "page-activity.example",
            "page-tied.example",
            "page-priority.example",
            "page-uncalculated.example",
        ]

    def test_rendered_activity_column_has_meter_tooltips_and_unavailable_state(self):
        with mock.patch("clist.resource_activity.get_resource_activity_scores") as calculation:
            response = resources(self.request())
        calculation.assert_not_called()
        soup = BeautifulSoup(response.content, "html.parser")
        activity_header = soup.select_one("#resources th[data-toggle='tooltip']")
        assert activity_header.get_text(strip=True) == "Activity"
        assert activity_header["title"] == "Recent contests, major events, and linked CLIST accounts"
        cells = {}
        for row in soup.select("#resources tr"):
            lead = row.select_one("td.resource .lead")
            if lead:
                cells[lead.get_text(strip=True)] = row.select("td")[1]

        high = cells[self.high_activity.host].select_one('[role="meter"]')
        assert high["aria-label"] == "Activity"
        assert high["aria-valuemin"] == "0"
        assert high["aria-valuemax"] == "100"
        assert high["aria-valuenow"] == "90.2"
        assert high["data-toggle"] == "tooltip"
        assert high["data-placement"] == "top"
        assert high["style"] == "--activity-score: 90.234%"
        assert high.select_one(".activity-meter-fill") is not None
        assert high.select_one(".activity-meter-track")["aria-hidden"] == "true"
        assert high["title"] == "90.2"
        assert high.get_text(strip=True) == ""

        low = cells[self.low_activity.host].select_one('[role="meter"]')
        assert low["aria-valuenow"] == "10.0"
        assert low["style"] == "--activity-score: 10.000%"
        assert low.select_one(".activity-meter-fill") is not None
        assert low["title"] == "10.0"
        assert low.get_text(strip=True) == ""

        zero = cells[self.high_priority.host].select_one('[role="meter"]')
        assert zero["aria-valuenow"] == "0.0"
        assert zero["style"] == "--activity-score: 0.000%"
        assert zero.select_one(".activity-meter-fill") is None
        assert zero["title"] == "0.0"
        assert zero.get_text(strip=True) == ""

        unavailable = cells[self.uncalculated.host]
        assert unavailable.select_one('[role="meter"]') is None
        assert unavailable.select_one('[data-toggle="tooltip"]')["title"] == "Activity has not been calculated"
        assert unavailable.get_text(strip=True) == "—"
        assert len(soup.select('#resources [role="meter"]')) == 4
        assert soup.select_one("#resources .activity-meter-value") is None
        assert soup.select_one("#resources .activity-score") is None
        assert soup.select_one('[data-column="activity"]') is None
