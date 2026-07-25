from types import SimpleNamespace
from unittest import mock

from django.test import RequestFactory, SimpleTestCase, override_settings

from clist.models import Resource
from true_coders.views import change, search


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
