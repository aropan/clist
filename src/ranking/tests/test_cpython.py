from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from ranking.management.modules import cpython


class CpythonUsersInfoTest(SimpleTestCase):
    def test_api_username_restores_canonical_case(self):
        resource = SimpleNamespace(url="https://kep.uz/")

        def query(url):
            return {"username": "Canonical"} if url.endswith("/info") else {}

        for user in ("canonical", "Canonical"):
            with self.subTest(user=user), mock.patch.object(cpython, "query", side_effect=query):
                (info,) = cpython.Statistic.get_users_infos([user], resource, [])

                assert info["info"]["username"] == "Canonical"
                assert info["canonical_key"] == "Canonical"
                if user == "Canonical":
                    assert "rename" not in info
                else:
                    assert info["rename"] == "Canonical"
