import inspect
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django_ratelimit.core import get_usage

from clist.models import Contest, Resource
from clist.templatetags.extras import profile_url
from pyclist.middleware import CustomRequest
from ranking.enums import AccountType
from ranking.management.modules import algoleague, atcoder, codechef, cpython, hackerrank, lightoj
from ranking.management.modules.common import BaseModule
from ranking.models import Account, AccountVerification, Module, Statistics, VerifiedAccount
from ranking.utils import rename_account
from true_coders.models import Coder, CoderList
from true_coders.views import (
    PROFILE_CONTESTS_PAGING_TEMPLATE,
    PROFILE_WRITERS_PAGING_TEMPLATE,
    _get_data_mixed_profile,
    account_verification,
    change,
    get_profile_context,
    get_ratings_data,
    search,
)
from true_coders.views import accounts as accounts_view

PROFILE_LINKS_MIDDLEWARE = [
    middleware
    for middleware in django_settings.MIDDLEWARE
    if middleware
    not in {
        "pyclist.middleware.DebugPermissionOnlyMiddleware",
        "silk.middleware.SilkyMiddleware",
    }
]


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


@override_settings(MIDDLEWARE=PROFILE_LINKS_MIDDLEWARE)
class ProfileContestLinksTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.coder = Coder.objects.create(username="ProfileLinksCoder")

        cls.member_resource = Resource.objects.create(
            host="member-profile-links.example",
            enable=True,
            url="https://member-profile-links.example/",
            icon_file="resources/test.png",
            icon_updated_at=now,
        )
        cls.user_resource = Resource.objects.create(
            host="user-profile-links.example",
            enable=True,
            url="https://user-profile-links.example/",
            icon_file="resources/test.png",
            icon_updated_at=now,
        )
        cls.member_account = Account.objects.create(
            resource=cls.member_resource,
            key="member-account",
            account_type=AccountType.MEMBER,
        )
        cls.user_account = Account.objects.create(resource=cls.user_resource, key="user-account")
        cls.member_account.coders.add(cls.coder)
        cls.user_account.coders.add(cls.coder)

        cls.member_contest = cls.create_contest(
            resource=cls.member_resource,
            title="Member contest",
            key="member-contest",
            end_time=now - timedelta(hours=1),
        )
        cls.user_contest = cls.create_contest(
            resource=cls.user_resource,
            title="User contest",
            key="user-contest",
            end_time=now - timedelta(hours=3),
        )
        cls.member_statistic = Statistics.objects.create(
            account=cls.member_account,
            contest=cls.member_contest,
            resource=cls.member_resource,
            place="1",
            place_as_int=1,
        )
        cls.user_statistic = Statistics.objects.create(
            account=cls.user_account,
            contest=cls.user_contest,
            resource=cls.user_resource,
            place="1",
            place_as_int=1,
        )

    @staticmethod
    def create_contest(resource, title, key, end_time):
        return Contest.objects.create(
            resource=resource,
            title=title,
            start_time=end_time - timedelta(hours=1),
            end_time=end_time,
            duration_in_secs=3600,
            url=f"https://{resource.host}/contest/{key}",
            key=key,
            host=resource.host,
            n_statistics=1,
        )

    def test_non_default_account_type_is_added_to_standings_link(self):
        profile_url = reverse("coder:profile", args=[self.coder.username])
        response = self.client.get(profile_url)

        assert response.status_code == 200
        content = response.content.decode()
        member_standings_url = reverse(
            "ranking:standings",
            args=["member-contest", self.member_contest.pk],
        )
        user_standings_url = reverse(
            "ranking:standings",
            args=["user-contest", self.user_contest.pk],
        )
        assert f'href="{profile_url}?resource={self.member_resource.pk}"' in content
        assert f'href="{profile_url}?resource={self.user_resource.pk}"' in content
        assert f'href="{member_standings_url}?account_type=member&amp;find_me={self.member_statistic.pk}"' in content
        assert f'href="{user_standings_url}?find_me={self.user_statistic.pk}"' in content

    def test_non_default_account_type_is_added_to_account_resource_link(self):
        member_response = self.client.get(
            reverse("coder:account", args=[self.member_account.key, self.member_resource.host])
        )
        user_response = self.client.get(reverse("coder:account", args=[self.user_account.key, self.user_resource.host]))

        assert member_response.status_code == 200
        assert user_response.status_code == 200
        member_resource_url = reverse("clist:resource", args=[self.member_resource.host])
        user_resource_url = reverse("clist:resource", args=[self.user_resource.host])
        assert f'href="{member_resource_url}?account_type=member"' in member_response.content.decode()
        assert f'href="{user_resource_url}"' in user_response.content.decode()
        assert f'href="{user_resource_url}?account_type=' not in user_response.content.decode()


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


class AccountBindingTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="account-binding-test")
        self.coder = Coder.objects.create(user=self.user, username=self.user.username, country=None)
        icon_patcher = mock.patch.object(Resource, "update_icon")
        icon_patcher.start()
        self.addCleanup(icon_patcher.stop)
        self.resource = Resource.objects.create(
            host="account-binding.example",
            url="https://account-binding.example/",
            enable=True,
            has_accounts_infos_update=True,
            has_account_verification=True,
        )
        self.module = Module.objects.create(
            resource=self.resource,
            path="ranking/management/modules/codeforces",
            max_delay_after_end=timedelta(days=1),
            delay_on_error=timedelta(minutes=1),
        )
        self.lookup = mock.Mock(return_value=[{"info": {"handle": "missing"}, "canonical_key": "missing"}])
        plugin = SimpleNamespace(
            Statistic=SimpleNamespace(get_users_infos=self.lookup, get_account_fields=BaseModule.get_account_fields)
        )
        plugin_patcher = mock.patch.object(Resource, "plugin", new_callable=mock.PropertyMock, return_value=plugin)
        plugin_patcher.start()
        self.addCleanup(plugin_patcher.stop)
        self.usage_patcher = mock.patch("true_coders.views.get_usage", return_value={"should_limit": False})
        self.usage = self.usage_patcher.start()
        self.addCleanup(self.usage_patcher.stop)

    def add_account(self, value="missing", account=None):
        data = {"pk": self.coder.pk, "name": "add-account", "value": value}
        if account is None:
            data["resource"] = self.resource.pk
        else:
            data["id"] = account.pk
        request = self.factory.post("/settings/change/", data)
        request.user = self.user
        return change(request)

    def assert_verification_redirect(self, response, account):
        assert response.status_code == 302
        assert json.loads(response.content) == {
            "message": "redirect",
            "url": reverse("coder:account_verification", kwargs={"key": account.key, "host": self.resource.host}),
        }
        assert not account.coders.filter(pk=self.coder.pk).exists()

    def verify_account(self, account):
        verification = AccountVerification.objects.create(coder=self.coder, account=account)
        self.lookup.return_value = [{"info": {"firstName": verification.text()}}]
        request = self.factory.post("/verification/", {"action": "verify"})
        request.user = self.user
        with mock.patch("true_coders.views.get_usage", return_value={"should_limit": False}):
            return account_verification(request, key=account.key, host=self.resource.host)

    def test_exact_local_account_does_not_use_discovery(self):
        account = Account.objects.create(resource=self.resource, key="missing")

        response = self.add_account()

        assert response.status_code == 200
        assert json.loads(response.content)["message"] == "add"
        assert account.coders.filter(pk=self.coder.pk).exists()
        self.lookup.assert_not_called()
        self.usage.assert_not_called()

    def test_case_insensitive_local_key_returns_suggestions_without_discovery(self):
        for index, (key, value) in enumerate((
            ("tourist", "TOURIST"),
            ("gennady.korotkevich", "GENNADY.KOROTKEVICH"),
            ("CaseSensitive", "casesensitive"),
        )):
            with self.subTest(key=key, value=value):
                account = Account.objects.create(resource=self.resource, key=key)
                self.lookup.return_value = [{"info": {"rating": 1500}}]

                response = self.add_account(value=value)

                assert response.status_code == 200
                assert json.loads(response.content) == {"message": "suggest", "accounts": [account.dict()]}
                assert Account.objects.count() == index + 1
                assert not account.coders.exists()
                self.lookup.assert_not_called()
                self.usage.assert_not_called()

    def test_account_id_does_not_use_discovery(self):
        account = Account.objects.create(resource=self.resource, key="missing")

        response = self.add_account(account=account)

        assert response.status_code == 200
        assert account.coders.filter(pk=self.coder.pk).exists()
        self.lookup.assert_not_called()
        self.usage.assert_not_called()

    def test_missing_module_does_not_use_discovery(self):
        self.module.delete()

        response = self.add_account()

        assert response.status_code == 400
        assert response.content == b"Account not found"
        assert not Account.objects.exists()
        self.lookup.assert_not_called()

    def test_required_resource_features_gate_discovery(self):
        for field in ("has_accounts_infos_update", "has_account_verification"):
            with self.subTest(field=field):
                setattr(self.resource, field, False)
                self.resource.save(update_fields=[field])

                response = self.add_account()

                assert response.status_code == 400
                assert response.content == b"Account not found"
                assert not Account.objects.exists()
                self.lookup.assert_not_called()
                setattr(self.resource, field, True)
                self.resource.save(update_fields=[field])

    def test_empty_handle_does_not_use_discovery(self):
        response = self.add_account(value="")

        assert response.status_code == 400
        assert not Account.objects.exists()
        self.lookup.assert_not_called()

    def test_discovery_creates_account_requiring_verification(self):
        response = self.add_account()

        account = Account.objects.get(resource=self.resource, key="missing")
        assert account.need_verification
        assert account.info == {}
        self.assert_verification_redirect(response, account)
        self.lookup.assert_called_once()
        kwargs = self.lookup.call_args.kwargs
        assert kwargs["users"] == ["missing"]
        assert kwargs["resource"] == self.resource
        (candidate,) = kwargs["accounts"]
        assert candidate.pk is None
        assert candidate.key == "missing"
        assert candidate.resource == self.resource
        self.usage.assert_called_once_with(mock.ANY, group="discover-account", key="user", rate="10/h", increment=True)

    def test_discovery_rate_limit_prevents_module_call_and_account_creation(self):
        self.usage.return_value = {"should_limit": True, "time_left": 60}

        response = self.add_account()

        assert response.status_code == 429
        assert response.content.startswith(b"Try again in ")
        assert not Account.objects.exists()
        self.lookup.assert_not_called()

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "account-binding-discovery-limit",
            }
        }
    )
    def test_discovery_budget_bounds_requests_and_is_scoped_to_user(self):
        cache.clear()
        self.lookup.side_effect = lambda users, **kwargs: [{"info": {"handle": users[0]}, "canonical_key": users[0]}]
        with (
            mock.patch("true_coders.views.get_usage", wraps=get_usage),
            mock.patch("django_ratelimit.core.time.time", return_value=1_700_000_000),
        ):
            for index in range(10):
                response = self.add_account(value=f"missing-{index}")
                assert response.status_code == 302

            response = self.add_account(value="missing-over-limit")

            assert response.status_code == 429
            assert self.lookup.call_count == 10
            assert Account.objects.count() == 10
            assert not Account.objects.filter(key="missing-over-limit").exists()

            local = Account.objects.get(key="missing-0")
            self.assert_verification_redirect(self.add_account(value=local.key), local)
            self.assert_verification_redirect(self.add_account(account=local), local)
            response = self.add_account(value=local.key.upper())
            assert response.status_code == 200
            assert json.loads(response.content) == {"message": "suggest", "accounts": [local.dict()]}
            assert self.lookup.call_count == 10

            self.user = User.objects.create_user(username="another-discovery-user")
            self.coder = Coder.objects.create(user=self.user, username=self.user.username, country=None)
            response = self.add_account(value="another-missing")

        assert response.status_code == 302
        assert self.lookup.call_count == 11
        assert Account.objects.count() == 11

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "account-binding-failed-discovery-limit",
            }
        }
    )
    def test_failed_discoveries_consume_the_budget(self):
        cache.clear()
        self.lookup.return_value = []
        with (
            mock.patch("true_coders.views.get_usage", wraps=get_usage),
            mock.patch("django_ratelimit.core.time.time", return_value=1_700_000_000),
        ):
            for index in range(10):
                response = self.add_account(value=f"missing-{index}")
                assert response.status_code == 400
                assert response.content == b"Account not found"

            response = self.add_account(value="missing-over-limit")

        assert response.status_code == 429
        assert self.lookup.call_count == 10
        assert not Account.objects.exists()

    def test_discovery_precedes_local_suggestions(self):
        Account.objects.create(resource=self.resource, key="missing-other")

        response = self.add_account()

        account = Account.objects.get(resource=self.resource, key="missing")
        self.assert_verification_redirect(response, account)
        self.lookup.assert_called_once()

    def test_unsuccessful_discovery_preserves_local_suggestions(self):
        account = Account.objects.create(resource=self.resource, key="missing-other")
        self.lookup.return_value = []

        response = self.add_account()

        assert response.status_code == 200
        assert json.loads(response.content) == {"message": "suggest", "accounts": [account.dict()]}
        assert Account.objects.count() == 1
        self.lookup.assert_called_once()

    def test_unsuccessful_discovery_preserves_suggestion_limit(self):
        for index in range(6):
            Account.objects.create(resource=self.resource, key=f"missing-{index}")
        self.lookup.return_value = []

        response = self.add_account()

        assert response.status_code == 400
        assert response.content == b"Too many accounts"
        assert Account.objects.count() == 6

    def test_unconfirmed_profiles_do_not_create_accounts(self):
        results = [
            [],
            [None],
            [{}],
            [{"info": {}}],
            [{"info": ["missing"]}],
            [{"skip": True, "info": {"handle": "missing"}}],
            [{"delete": True, "info": {"handle": "missing"}}],
            [{"rename": "canonical"}],
            [{"info": {"handle": "missing"}}],
        ]
        for key in (None, "", 123, "x" * 401):
            results.append([{"info": {"handle": "missing"}, "rename": key}])
            results.append([{"info": {"handle": "missing"}, "canonical_key": key}])
        for result in results:
            with self.subTest(result=result):
                self.lookup.return_value = result

                response = self.add_account()

                assert response.status_code == 400
                assert response.content == b"Account not found"
                assert not Account.objects.exists()

    def test_profile_without_canonical_key_preserves_local_suggestions(self):
        account = Account.objects.create(resource=self.resource, key="missing-suggestion")
        self.lookup.return_value = [{"info": {"rating": 1500}}]

        response = self.add_account()

        assert response.status_code == 200
        assert json.loads(response.content) == {"message": "suggest", "accounts": [account.dict()]}
        assert Account.objects.count() == 1
        assert not account.coders.exists()

    def test_atcoder_discovery_restores_new_handle_case(self):
        self.resource.profile_url = "https://atcoder.jp/users/{account}"
        self.resource.save(update_fields=["profile_url"])
        self.lookup.side_effect = atcoder.Statistic.get_users_infos
        page = '<a href="/users/tourist" class="username"><span>tourist</span></a>'

        with mock.patch.object(atcoder.Statistic, "_get", return_value=page):
            response = self.add_account(value="TOURIST")

        account = Account.objects.get(resource=self.resource, key="tourist")
        self.assert_verification_redirect(response, account)
        assert account.need_verification
        assert Account.objects.count() == 1

    def test_codechef_discovery_restores_new_handle_case(self):
        self.lookup.side_effect = codechef.Statistic.get_users_infos
        page = 'jQuery.extend(Drupal.settings,{"currentUser":"gennady.korotkevich","date_versus_rating":{"all":[]}});'

        with (
            mock.patch.object(codechef.REQ, "with_proxy", return_value=mock.MagicMock()),
            mock.patch.object(
                codechef.Statistic,
                "fetch_profle_page",
                return_value=(page, "https://www.codechef.com/users/GENNADY.KOROTKEVICH"),
            ),
        ):
            response = self.add_account(value="GENNADY.KOROTKEVICH")

        account = Account.objects.get(resource=self.resource, key="gennady.korotkevich")
        self.assert_verification_redirect(response, account)
        assert account.need_verification
        assert Account.objects.count() == 1

    def test_module_exception_uses_local_not_found(self):
        self.lookup.side_effect = RuntimeError("upstream details")

        with mock.patch("true_coders.views.logger"):
            response = self.add_account()

        assert response.status_code == 400
        assert response.content == b"Account not found"
        assert not Account.objects.exists()

    def test_generator_exception_preserves_local_suggestions(self):
        account = Account.objects.create(resource=self.resource, key="missing-other")

        def infos(**kwargs):
            raise KeyError("missing profile field")
            yield

        self.lookup.side_effect = infos
        with mock.patch("true_coders.views.logger"):
            response = self.add_account()

        assert response.status_code == 200
        assert json.loads(response.content) == {"message": "suggest", "accounts": [account.dict()]}
        assert Account.objects.count() == 1

    def test_lightoj_missing_profile_fields_preserve_name_suggestions(self):
        self.resource.profile_url = "https://lightoj.com/{kind}/{slug}"
        self.resource.save(update_fields=["profile_url"])
        account = Account.objects.create(
            resource=self.resource,
            key="123",
            name="Missing Person",
            info={"profile_url": {"kind": "user", "slug": "missing-person"}},
        )
        self.lookup.side_effect = lightoj.Statistic.get_users_infos

        with mock.patch.object(lightoj.REQ, "get") as request_get, mock.patch("true_coders.views.logger"):
            response = self.add_account()

        assert response.status_code == 200
        assert json.loads(response.content) == {"message": "suggest", "accounts": [account.dict()]}
        assert Account.objects.count() == 1
        request_get.assert_not_called()

    def test_discovery_preserves_profile_url_rating_and_account_type(self):
        self.resource.profile_url = "https://leetcode{_domain}/u/{_handle}/"
        self.resource.save(update_fields=["profile_url"])
        info = {"profile_url": {"_domain": ".com", "_handle": "missing"}, "rating": 1500, "is_team": True}
        self.lookup.return_value = [
            {
                "info": dict(info, delta=timedelta(days=7), download_avatar_url_="https://example.com/avatar"),
                "canonical_key": "missing@.com",
                "special_info_fields": {"name_ru"},
            }
        ]

        response = self.add_account(value="missing@.com")

        account = Account.objects.get(resource=self.resource, key="missing@.com")
        self.assert_verification_redirect(response, account)
        assert account.info == info
        assert account.rating == 1500
        assert account.rating50 == 30
        assert account.account_type == AccountType.TEAM
        assert 'href="https://leetcode.com/u/missing/"' in profile_url(account, inner="your profile")

    def test_discovered_rated_account_keeps_verification_single_account_limit(self):
        self.resource.has_multi_account = True
        self.resource.save(update_fields=["has_multi_account"])
        existing = Account.objects.create(resource=self.resource, key="existing", info={"rating": 1800})
        existing.coders.add(self.coder)
        self.lookup.return_value = [{"info": {"rating": 1500}, "canonical_key": "missing"}]
        response = self.add_account()
        account = Account.objects.get(resource=self.resource, key="missing")
        self.assert_verification_redirect(response, account)
        assert account.rating == 1500
        request = self.factory.post("/verification/", {"action": "verify"})
        request.user = self.user

        response = account_verification(request, key=account.key, host=self.resource.host)

        assert response.status_code == 400
        assert response.content.decode() == f"Allow only one account for {self.resource.host} resource"
        assert list(self.coder.account_set.values_list("pk", flat=True)) == [existing.pk]
        assert not AccountVerification.objects.exists()
        self.lookup.assert_called_once()

    def test_kep_canonical_case_returns_local_suggestion(self):
        account = Account.objects.create(resource=self.resource, key="Missing")
        self.lookup.side_effect = cpython.Statistic.get_users_infos

        def query(url):
            return {"username": "Missing"} if url.endswith("/info") else {}

        with mock.patch.object(cpython, "query", side_effect=query) as request_query:
            response = self.add_account()

        assert response.status_code == 200
        assert json.loads(response.content) == {"message": "suggest", "accounts": [account.dict()]}
        assert not account.coders.exists()
        assert Account.objects.count() == 1
        self.lookup.assert_not_called()
        request_query.assert_not_called()

    def test_hackerrank_canonical_case_returns_local_suggestion(self):
        account = Account.objects.create(resource=self.resource, key="Canonical")
        self.lookup.side_effect = hackerrank.Statistic.get_users_infos

        def get(url):
            if url.endswith("/profile"):
                return json.dumps({"model": {"username": "Canonical"}})
            if url.endswith("/rating_histories_elo"):
                return json.dumps({"models": []})
            raise AssertionError(url)

        with mock.patch.object(hackerrank.Statistic, "get", side_effect=get) as request_get:
            response = self.add_account(value="canonical")

        assert response.status_code == 200
        assert json.loads(response.content) == {"message": "suggest", "accounts": [account.dict()]}
        assert not account.coders.exists()
        assert Account.objects.count() == 1
        self.lookup.assert_not_called()
        request_get.assert_not_called()

    def test_algoleague_discovery_preserves_working_profile_link(self):
        self.resource.profile_url = "https://algoleague.com/{type}/{account}/"
        self.resource.save(update_fields=["profile_url"])
        self.lookup.side_effect = algoleague.Statistic.get_users_infos

        with mock.patch.object(
            algoleague.REQ, "get", return_value={"profile": {"userName": "missing", "name": "Missing"}}
        ):
            response = self.add_account()

        account = Account.objects.get(resource=self.resource, key="missing")
        self.assert_verification_redirect(response, account)
        assert 'href="https://algoleague.com/profile/missing/"' in profile_url(account, inner="your profile")

    def test_discovered_account_requires_verification_after_rename(self):
        self.add_account()
        old_account = Account.objects.get(resource=self.resource, key="missing")
        canonical_account = Account.objects.create(resource=self.resource, key="canonical")

        account = rename_account(old_account, canonical_account)
        response = self.add_account(value="canonical")

        account.refresh_from_db()
        assert account.need_verification
        self.assert_verification_redirect(response, account)
        assert not VerifiedAccount.objects.exists()
        assert Account.objects.count() == 1
        self.lookup.assert_called_once()

    def test_verified_owner_can_rebind_discovered_account(self):
        self.add_account()
        account = Account.objects.get(resource=self.resource, key="missing")
        assert self.verify_account(account).status_code == 200

        for request_account in (None, account):
            with self.subTest(account=request_account):
                request = self.factory.post(
                    "/settings/change/", {"pk": self.coder.pk, "name": "delete-account", "id": account.pk}
                )
                request.user = self.user
                assert change(request).status_code == 200

                response = self.add_account(account=request_account)

                assert response.status_code == 200
                assert json.loads(response.content)["message"] == "add"
                assert account.coders.filter(pk=self.coder.pk).exists()
                assert VerifiedAccount.objects.filter(coder=self.coder, account=account).exists()
                account.refresh_from_db()
                assert account.need_verification
        assert self.lookup.call_count == 2

    def test_another_user_cannot_reuse_discovered_account_verification(self):
        self.add_account()
        account = Account.objects.get(resource=self.resource, key="missing")
        assert self.verify_account(account).status_code == 200
        account.coders.remove(self.coder)
        self.user = User.objects.create_user(username="another-account-binding-user")
        self.coder = Coder.objects.create(user=self.user, username=self.user.username, country=None)

        response = self.add_account()

        self.assert_verification_redirect(response, account)
        assert not account.coders.exists()
        assert not VerifiedAccount.objects.filter(coder=self.coder, account=account).exists()
        assert self.lookup.call_count == 2

    def test_verified_owner_can_rebind_after_rename(self):
        self.add_account()
        account = Account.objects.get(resource=self.resource, key="missing")
        assert self.verify_account(account).status_code == 200
        canonical = Account.objects.create(resource=self.resource, key="canonical")

        account = rename_account(account, canonical)
        assert VerifiedAccount.objects.filter(coder=self.coder, account=account).exists()
        account.coders.remove(self.coder)
        response = self.add_account(value="canonical")

        assert response.status_code == 200
        assert account.coders.filter(pk=self.coder.pk).exists()
        account.refresh_from_db()
        assert account.need_verification
        assert self.lookup.call_count == 2

    def test_canonical_key_is_used_for_creation_and_redirect(self):
        self.lookup.return_value = [{"info": {"handle": "canonical"}, "rename": "canonical"}]

        response = self.add_account()

        account = Account.objects.get(resource=self.resource, key="canonical")
        self.assert_verification_redirect(response, account)
        assert account.need_verification
        assert Account.objects.count() == 1

    def test_existing_canonical_account_is_not_overwritten(self):
        account = Account.objects.create(resource=self.resource, key="canonical", info={"name": "Stored name"})
        self.lookup.return_value = [{"info": {"name": "New name"}, "rename": "canonical"}]

        response = self.add_account()

        account.refresh_from_db()
        assert response.status_code == 200
        assert json.loads(response.content)["account"]["pk"] == account.pk
        assert account.info == {"name": "Stored name"}
        assert not account.need_verification
        assert account.coders.filter(pk=self.coder.pk).exists()
        assert Account.objects.count() == 1

    def test_existing_canonical_ownership_requires_verification(self):
        other_user = User.objects.create_user(username="other-account-owner")
        other_coder = Coder.objects.create(user=other_user, username=other_user.username, country=None)
        account = Account.objects.create(resource=self.resource, key="canonical")
        account.coders.add(other_coder)
        self.lookup.return_value = [{"info": {"handle": "canonical"}, "rename": "canonical"}]

        response = self.add_account()

        self.assert_verification_redirect(response, account)
        assert list(account.coders.values_list("pk", flat=True)) == [other_coder.pk]
        assert Account.objects.count() == 1

    def test_retries_by_handle_and_id_still_require_verification(self):
        self.add_account()
        account = Account.objects.get(resource=self.resource, key="missing")

        for request_account in (None, account):
            with self.subTest(account=request_account):
                response = self.add_account(account=request_account)

                self.assert_verification_redirect(response, account)
                assert Account.objects.count() == 1
        self.lookup.assert_called_once()

    def test_single_account_restriction_applies_to_discovery(self):
        existing = Account.objects.create(resource=self.resource, key="existing")
        existing.coders.add(self.coder)

        response = self.add_account()

        assert response.status_code == 400
        assert response.content.decode() == f"Allow only one account for {self.resource.host}"
        assert list(self.coder.account_set.values_list("pk", flat=True)) == [existing.pk]
        assert Account.objects.count() == 1
        self.lookup.assert_not_called()
        self.usage.assert_not_called()

    def test_discovered_account_can_complete_existing_verification(self):
        self.add_account()
        account = Account.objects.get(resource=self.resource, key="missing")

        response = self.verify_account(account)

        assert response.status_code == 200
        assert response.content == b"ok"
        assert account.coders.filter(pk=self.coder.pk).exists()
        assert VerifiedAccount.objects.filter(coder=self.coder, account=account).exists()
        assert self.lookup.call_count == 2


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

    def test_rating_history_includes_only_non_default_account_type(self):
        resource = self.create_resource("account-type-rating.example")
        contest = self.create_contest(resource, is_rated=True)
        member = Account.objects.create(resource=resource, key="member", account_type=AccountType.MEMBER)
        user = Account.objects.create(resource=resource, key="user")
        for account in (member, user):
            Statistics.objects.create(
                account=account,
                contest=contest,
                resource=resource,
                addition={"old_rating": 1500, "new_rating": 1600, "rating_change": 100},
            )

        ratings = get_ratings_data(
            request=self.request(),
            statistics=Statistics.objects.filter(account__in=(member, user)),
        )

        resources = ratings["data"]["resources"]
        member_rating = resources[f"{resource.host} #{member.pk}"]["data"][0][0]
        user_rating = resources[f"{resource.host} #{user.pk}"]["data"][0][0]
        assert member_rating["account_type"] == "member"
        assert "account_type" not in user_rating
