from django.test import RequestFactory, SimpleTestCase

from ranking.views import versus


class VersusTest(SimpleTestCase):
    def test_invalid_remove_index_is_rejected(self):
        request = RequestFactory().get("/versus/", {"remove": "not-an-integer"})
        response = versus(request, "first/vs/second")
        assert response.status_code == 400
