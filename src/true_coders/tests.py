import inspect
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import AnonymousUser, User
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from clist.models import Contest, Resource
from pyclist.middleware import CustomRequest
from ranking.models import Account, Statistics
from true_coders.models import Coder, CoderList
from true_coders.views import (
    PROFILE_CONTESTS_PAGING_TEMPLATE,
    PROFILE_WRITERS_PAGING_TEMPLATE,
    _get_data_mixed_profile,
    change,
    get_profile_context,
    get_ratings_data,
    search,
)
from true_coders.views import accounts as accounts_view


class SettingsViewTest(TestCase):
    tabs = (
        "preferences",
        "social",
        "accounts",
        "filters",
        "notifications",
        "lists",
        "chats",
        "calendars",
        "subscriptions",
    )

    def setUp(self):
        self.user = User.objects.create_superuser(username="settings-test", password="test-password")
        self.coder = Coder.objects.create(user=self.user, username=self.user.username, country=None)
        self.client.force_login(self.user)

    def assert_all_tabs(self, response, expected_active_tab):
        assert response.status_code == 200
        content = response.content.decode()
        rendered_tabs = [tab for tab in self.tabs if f'id="{tab}-tab"' in content]
        active_tabs = [tab for tab in self.tabs if f'id="{tab}-tab" class="tab-pane active"' in content]
        assert rendered_tabs == list(self.tabs)
        assert active_tabs == [expected_active_tab]

    def test_default_url_renders_all_tabs(self):
        response = self.client.get(reverse("coder:settings"))

        self.assert_all_tabs(response, "preferences")
        for tab in self.tabs:
            assert f'href="#{tab}-tab" data-toggle="tab"' in response.content.decode()

    def test_each_url_renders_all_tabs_with_requested_tab_active(self):
        for tab in self.tabs:
            with self.subTest(tab=tab):
                response = self.client.get(reverse("coder:settings", kwargs={"tab": tab}))

                self.assert_all_tabs(response, tab)

    def test_accounts_support_account_without_country(self):
        with mock.patch.object(Resource, "update_icon"):
            resource = Resource.objects.create(
                host="settings-account.example",
                enable=True,
                url="https://settings-account.example/",
            )
        account = Account.objects.create(
            resource=resource,
            key="countryless-account",
            country=None,
            info={"custom_countries_": {"BY": "BPR"}},
        )
        account.coders.add(self.coder)

        response = self.client.get(reverse("coder:settings"))

        self.assert_all_tabs(response, "preferences")
        assert "countryless-account" in response.content.decode()

    def test_notification_post_to_default_url_renders_notifications_on_error(self):
        response = self.client.post(reverse("coder:settings"), {"action": "notification"})

        self.assert_all_tabs(response, "notifications")


@override_settings(DEFAULT_COUNT_QUERY_=10, DEFAULT_COUNT_LIMIT_=100, THEMES_=["default"])
class SearchPaginationTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def get_response(self, **params):
        return search(self.factory.get("/settings/search/", {"query": "themes", **params}))

    def test_defaults_are_valid(self):
        assert self.get_response().status_code == 200

    def test_count_is_capped(self):
        queryset = mock.MagicMock()
        queryset.order_by.return_value = queryset
        queryset.__getitem__.return_value = []
        with mock.patch.object(Resource, "priority_objects") as manager:
            manager.all.return_value = queryset
            response = search(self.factory.get("/settings/search/", {"query": "resources", "count": 101, "page": 2}))

        assert response.status_code == 200
        queryset.__getitem__.assert_called_once_with(slice(100, 200))

    def test_non_integer_values_are_rejected(self):
        for field in ("count", "page"):
            with self.subTest(field=field):
                assert self.get_response(**{field: "not-an-integer"}).status_code == 400

    def test_non_positive_values_are_rejected(self):
        for field in ("count", "page"):
            for value in (0, -1):
                with self.subTest(field=field, value=value):
                    assert self.get_response(**{field: value}).status_code == 400


class ProfileLookupTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.resource = Resource.objects.create(
            host="profile-lookup.example",
            enable=True,
            url="https://profile-lookup.example/",
            color="#336699",
            icon_file="resources/test.png",
            icon_updated_at=now,
        )
        cls.account = Account.objects.create(resource=cls.resource, key="ShortKey")
        cls.second_account = Account.objects.create(resource=cls.resource, key="SecondKey")
        cls.coder = Coder.objects.create(username="ShortCoder")
        cls.writer = Contest.objects.create(
            resource=cls.resource,
            title="Profile writer",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            duration_in_secs=3600,
            url="https://profile-lookup.example/contest",
            key="profile-writer",
            host=cls.resource.host,
        )

    def test_mixed_profile_batches_account_lookups_in_query_order(self):
        request = CustomRequest(RequestFactory().get("/profile/"))
        request.user = AnonymousUser()
        query = [
            f"{self.resource.host}:{self.second_account.key}",
            f"{self.resource.host}:{self.account.key}",
        ]

        with CaptureQueriesContext(connection) as queries:
            data = _get_data_mixed_profile(request, query)

        account_queries = [item["sql"] for item in queries if 'FROM "ranking_account"' in item["sql"]]
        assert len(account_queries) == 1
        assert account_queries[0].count('"ranking_account"."key" =') == 2
        assert data["profiles"] == [self.second_account, self.account]

    def test_mixed_profile_preserves_account_and_coder_query_order(self):
        request = CustomRequest(RequestFactory().get("/profile/"))
        request.user = AnonymousUser()
        query = [
            f"{self.resource.host}:{self.second_account.key}",
            self.coder.username,
            f"{self.resource.host}:{self.account.key}",
        ]

        data = _get_data_mixed_profile(request, query)

        assert data["profiles"] == [self.second_account, self.coder, self.account]

    def test_contest_paging_context_skips_auxiliary_queries(self):
        request = CustomRequest(RequestFactory().get("/account/"))
        request.user = AnonymousUser()
        request.session = {}

        with (
            mock.patch("true_coders.views.get_medals_for_profile_context") as medals,
            mock.patch("true_coders.views.make_chart") as make_chart,
        ):
            context = get_profile_context(
                request,
                Statistics.objects.none(),
                Contest.objects.none(),
                Resource.objects.none(),
                template=PROFILE_CONTESTS_PAGING_TEMPLATE,
            )

        medals.assert_not_called()
        make_chart.assert_not_called()
        assert context["history_resources"] == []
        assert context["show_history_ratings"] is False

    def test_writers_paging_context_keeps_writers_and_skips_aggregates(self):
        request = CustomRequest(RequestFactory().get("/account/"))
        request.user = AnonymousUser()
        request.session = {}

        with (
            mock.patch("true_coders.views.get_medals_for_profile_context") as medals,
            mock.patch("true_coders.views.make_chart") as make_chart,
        ):
            context = get_profile_context(
                request,
                Statistics.objects.none(),
                Contest.objects.filter(pk=self.writer.pk),
                Resource.objects.filter(pk=self.resource.pk),
                template=PROFILE_WRITERS_PAGING_TEMPLATE,
            )

        medals.assert_not_called()
        make_chart.assert_not_called()
        assert list(context["writers"]) == [self.writer]
        assert context["history_resources"] == []
        assert context["show_history_ratings"] is False


class CoderListFilterTest(TestCase):
    def test_empty_anonymous_filter_uses_no_query(self):
        with CaptureQueriesContext(connection) as queries:
            coder_lists, uuids = CoderList.filter_for_coder_and_uuids(coder=None, uuids=[])
            coder_lists = list(coder_lists)

        assert coder_lists == []
        assert uuids == []
        assert len(queries) == 0


class AccountsContestFilterTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.update_icon_patcher = mock.patch.object(Resource, "update_icon")
        cls.update_icon_patcher.start()
        cls.addClassCleanup(cls.update_icon_patcher.stop)
        cls.resource = Resource.objects.create(
            host="accounts-filter.example",
            enable=True,
            url="https://accounts-filter.example/",
        )
        cls.account = Account.objects.create(resource=cls.resource, key="selected")
        cls.other_account = Account.objects.create(resource=cls.resource, key="not-selected")
        cls.contest = Contest.objects.create(
            resource=cls.resource,
            title="Accounts filter contest",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            duration_in_secs=3600,
            url="https://accounts-filter.example/contest/1",
            key="accounts-filter-1",
            host=cls.resource.host,
        )
        cls.second_contest = Contest.objects.create(
            resource=cls.resource,
            title="Second accounts filter contest",
            start_time=now - timedelta(hours=4),
            end_time=now - timedelta(hours=3),
            duration_in_secs=3600,
            url="https://accounts-filter.example/contest/2",
            key="accounts-filter-2",
            host=cls.resource.host,
        )
        for contest in (cls.contest, cls.second_contest):
            Statistics.objects.create(
                account=cls.account,
                contest=contest,
                resource=cls.resource,
                place="1",
                place_as_int=1,
            )

    @staticmethod
    def get_accounts_queryset(*contest_ids, sort=True):
        params = {"contest": contest_ids}
        if sort:
            params.update({"sort_column": "account", "sort_order": "asc"})
        request = CustomRequest(
            RequestFactory().get(
                "/accounts/",
                params,
            )
        )
        request.user = AnonymousUser()
        request.as_coder = None
        request.user_agent = SimpleNamespace(is_mobile=False)
        _, context = inspect.unwrap(accounts_view)(request)
        return context["accounts"]

    def test_single_contest_account_order_uses_statistics_join(self):
        accounts = self.get_accounts_queryset(self.contest.pk)
        sql = str(accounts.query)

        assert 'INNER JOIN "ranking_statistics"' in sql
        assert 'ORDER BY "ranking_account"."key" ASC' in sql
        assert list(accounts.values_list("pk", flat=True)) == [self.account.pk]

    def test_single_contest_default_order_uses_statistics_join(self):
        accounts = self.get_accounts_queryset(self.contest.pk, sort=False)
        sql = str(accounts.query)

        assert 'INNER JOIN "ranking_statistics"' in sql
        assert accounts.query.order_by == ("selected_place",)
        assert list(accounts.values_list("pk", flat=True)) == [self.account.pk]

    def test_multiple_contests_do_not_duplicate_accounts(self):
        accounts = self.get_accounts_queryset(self.contest.pk, self.second_contest.pk)

        assert list(accounts.values_list("pk", flat=True)) == [self.account.pk]


class ChangeIntegerValidationTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def post(self, data):
        request = self.factory.post("/settings/change/", data)
        request.user = SimpleNamespace(is_authenticated=True, coder=SimpleNamespace(id=1))
        return change(request)

    def test_invalid_coder_id_is_rejected(self):
        response = self.post({"pk": "not-an-integer", "name": "theme", "value": "default"})
        assert response.status_code == 400

    def test_invalid_add_account_resource_is_rejected(self):
        response = self.post({"pk": "1", "name": "add-account", "resource": "", "value": "handle"})
        assert response.status_code == 400


class RatingsDataTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.resource_icon_patcher = mock.patch.object(Resource, "update_icon")
        self.resource_icon_patcher.start()
        self.addCleanup(self.resource_icon_patcher.stop)

    def create_resource(self, host, *, external=False):
        return Resource.objects.create(
            host=host,
            enable=True,
            url=f"https://{host}/",
            has_rating_history=True,
            info={"ratings": {"external": external}},
        )

    def create_contest(self, resource, *, is_rated):
        now = timezone.now()
        return Contest.objects.create(
            resource=resource,
            title="Rating history test",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            url=f"https://{resource.host}/contest",
            key="rating-history-test",
            host=resource.host,
            is_rated=is_rated,
        )

    def request(self):
        request = self.factory.get("/ratings/")
        request.user = AnonymousUser()
        return request

    def test_external_rating_history_is_split_by_account(self):
        resource = self.create_resource("external-rating.example", external=True)
        contest = self.create_contest(resource, is_rated=False)
        accounts = [
            Account.objects.create(resource=resource, key=key, info={"_rating_data": key})
            for key in ("first", "second")
        ]
        for account in accounts:
            Statistics.objects.create(account=account, contest=contest, resource=resource)

        def get_rating_history(_rating_data, stat, _resource, **_kwargs):
            return [{"date": contest.end_time, "new_rating": stat.account_id}]

        plugin = SimpleNamespace(Statistic=SimpleNamespace(get_rating_history=get_rating_history))
        with mock.patch.object(Resource, "plugin", new_callable=mock.PropertyMock, return_value=plugin):
            ratings = get_ratings_data(
                request=self.request(),
                statistics=Statistics.objects.filter(account__in=accounts),
            )

        resources = ratings["data"]["resources"]
        assert set(resources) == {f"{resource.host} #{account.pk}" for account in accounts}
        for account in accounts:
            resource_info = resources[f"{resource.host} #{account.pk}"]
            assert resource_info["account_pk"] == account.pk
            assert resource_info["account_name"] == account.key

    def test_global_rating_resource_does_not_require_account(self):
        resource = self.create_resource("rated.example")
        contest = self.create_contest(resource, is_rated=True)
        account = Account.objects.create(resource=resource, key="rated-user")
        Statistics.objects.create(
            account=account,
            contest=contest,
            resource=resource,
            addition={"old_rating": 1000, "rating_change": 100, "new_rating": 1100},
            global_rating_change=50,
            new_global_rating=1200,
        )

        ratings = get_ratings_data(
            request=self.request(),
            statistics=Statistics.objects.filter(account=account),
            with_global=True,
        )

        resources = ratings["data"]["resources"].values()
        global_resource = next(resource_info for resource_info in resources if "account_pk" not in resource_info)
        assert "account_name" not in global_resource
