from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from ranking.management.modules import algoleague
from ranking.models import Account


class AlgoLeagueUsersInfoTest(SimpleTestCase):
    def test_profile_result_contains_profile_link_type(self):
        account = Account(key="missing")
        with mock.patch.object(algoleague.REQ, "get", return_value={"profile": {"name": "Missing"}}):
            (info,) = algoleague.Statistic.get_users_infos([account.key], None, [account])

        assert info["info"]["profile_url"] == {"type": "profile"}
        account.info = info["info"]
        resource = SimpleNamespace(profile_url="https://algoleague.com/{type}/{account}/")
        assert account.profile_url(resource) == "https://algoleague.com/profile/missing/"

    def test_empty_and_invalid_profiles_return_skip(self):
        for profile in ({}, None, [], "unconfirmed"):
            with (
                self.subTest(profile=profile),
                mock.patch.object(algoleague.REQ, "get", return_value={"profile": profile}),
            ):
                infos = list(algoleague.Statistic.get_users_infos(["missing"], None, [Account(key="missing")]))

                assert infos == [{"skip": True}]
