import json
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from ranking.management.modules import hackerrank


class HackerRankUsersInfoTest(SimpleTestCase):
    def test_api_username_restores_canonical_case(self):
        resource = SimpleNamespace(url="https://www.hackerrank.com/")

        def get(url):
            if url.endswith("/profile"):
                return json.dumps({"model": {"username": "Canonical"}})
            if url.endswith("/rating_histories_elo"):
                return json.dumps({"models": []})
            raise AssertionError(url)

        for user in ("canonical", "Canonical"):
            with self.subTest(user=user), mock.patch.object(hackerrank.Statistic, "get", side_effect=get):
                (info,) = hackerrank.Statistic.get_users_infos([user], resource, [])
                assert info["canonical_key"] == "Canonical"

                if user == "Canonical":
                    assert "rename" not in info
                else:
                    assert info["rename"] == "Canonical"
