from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from clist.management.commands.set_resources_accounts import get_resource_medal_fields
from clist.models import Contest, Resource
from ranking.enums import AccountType
from ranking.models import Account, Statistics


class ResourceAccountMedalsTest(TestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(Resource, "update_icon")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_empty_custom_medal_mapping_is_rejected(self):
        resource = SimpleNamespace(
            host="custom-medals.example.com",
            accounts_fields={"medal_fields": {"member": {}}},
        )

        with self.assertRaisesMessage(ValueError, "medal fields for member must not be empty"):
            get_resource_medal_fields(resource)

    def test_custom_medal_fields_are_aggregated_for_configured_account_type(self):
        resource = Resource.objects.create(
            host="custom-medals.example.com",
            url="https://custom-medals.example.com/",
            enable=True,
            has_statistic_medal=True,
            has_statistic_place=False,
            accounts_fields={
                "medal_fields": {
                    "member": {
                        "n_gold": "n_gold",
                        "n_silver": "n_silver",
                        "n_bronze": "n_bronze",
                        "n_other_medals": "n_honorable",
                    }
                }
            },
        )
        end_time = timezone.now() - timedelta(days=1)
        contests = [
            Contest.objects.create(
                resource=resource,
                title=f"Contest {index}",
                start_time=end_time - timedelta(hours=5),
                end_time=end_time,
                duration_in_secs=5 * 60 * 60,
                url=f"https://custom-medals.example.com/{index}",
                host=resource.host,
                key=str(index),
            )
            for index in range(2)
        ]
        member = Account.objects.create(
            resource=resource,
            key="member",
            account_type=AccountType.MEMBER,
            info={"is_member": True},
        )
        user = Account.objects.create(resource=resource, key="user")
        Statistics.objects.create(
            resource=resource,
            contest=contests[0],
            account=member,
            place="1",
            place_as_int=1,
            addition={"n_gold": 2, "n_silver": 1, "n_honorable": 1},
        )
        Statistics.objects.create(
            resource=resource,
            contest=contests[1],
            account=member,
            place="2",
            place_as_int=2,
            addition={"n_bronze": 2},
        )
        Statistics.objects.create(
            resource=resource,
            contest=contests[0],
            account=user,
            place="1",
            place_as_int=1,
            medal="gold",
            addition={"n_gold": 100},
        )

        call_command("set_resources_accounts", resources=[resource.host], stdout=StringIO())

        member.refresh_from_db()
        assert member.n_win == 1
        assert member.n_gold == 2
        assert member.n_silver == 1
        assert member.n_bronze == 2
        assert member.n_medals == 5
        assert member.n_other_medals == 1

        user.refresh_from_db()
        assert user.n_win == 1
        assert user.n_gold == 1
        assert user.n_silver is None
        assert user.n_bronze is None
        assert user.n_medals == 1
        assert user.n_other_medals is None
