from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from clist.models import Contest, Resource
from ranking.models import Account, Statistics
from true_coders.views import change, get_ratings_data, search


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
