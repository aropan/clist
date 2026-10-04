import json
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from ranking.management.modules import topcoder
from utils.requester import FailOnGetResponse


class TopcoderUsersInfoTest(SimpleTestCase):
    def get_infos(self, response=None, user="canonical", error=None):
        req = SimpleNamespace(
            get=mock.Mock(return_value=json.dumps(response), side_effect=error),
            proxer=SimpleNamespace(set_connect_func=mock.Mock(), proxy_address=None),
        )
        with mock.patch.object(topcoder.REQ, "with_proxy", return_value=nullcontext(req)):
            return list(topcoder.Statistic.get_users_infos([user]))

    def test_json_not_found_returns_delete(self):
        assert self.get_infos({"error": {"value": 404}}) == [{"delete": True}]

    def test_error_and_unconfirmed_responses_return_skip(self):
        for response in (None, [], {}, {"ratingSummary": []}, {"error": {"value": 500}}, {"error": "unavailable"}):
            with self.subTest(response=response):
                assert self.get_infos(response) == [{"skip": True, "delta": timedelta(days=7)}]

    def test_http_failures_keep_existing_handling(self):
        for code, expected in ((404, {"delete": True}), (500, {"skip": True})):
            with self.subTest(code=code):
                error = FailOnGetResponse(SimpleNamespace(code=code))
                assert self.get_infos(error=error) == [expected]

    def test_api_handle_restores_canonical_case(self):
        assert self.get_infos({"handle": "Canonical"}) == [
            {
                "info": {"handle": "Canonical"},
                "canonical_key": "Canonical",
                "rename": "Canonical",
            }
        ]

    def test_canonical_handle_does_not_request_rename(self):
        assert self.get_infos({"handle": "Canonical"}, user="Canonical") == [
            {"info": {"handle": "Canonical"}, "canonical_key": "Canonical"}
        ]
