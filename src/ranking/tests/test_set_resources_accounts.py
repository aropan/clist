from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from clist.management.commands.set_resources_accounts import get_resource_medal_fields, update_medal_win_equals_gold
from clist.models import Contest, Resource
from ranking.enums import AccountType
from ranking.models import Account, CountryAccount, Statistics
from true_coders.models import Coder, CoderList, ListGroup, ListValue


class ResourceAccountMedalsTest(TestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(Resource, "update_icon")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.resource_index = 0
        self.statistic_index = 0

    def create_resource(self, **kwargs):
        self.resource_index += 1
        fields = {
            "host": f"medals-{self.resource_index}.example.com",
            "url": f"https://medals-{self.resource_index}.example.com/",
            "enable": True,
            "has_statistic_medal": True,
            "has_statistic_place": False,
        }
        fields.update(kwargs)
        return Resource.objects.create(**fields)

    def create_statistic(self, resource, place=1, medal="gold", account=None, addition=None):
        self.statistic_index += 1
        end_time = timezone.now() - timedelta(days=1)
        contest = Contest.objects.create(
            resource=resource,
            title="Medal contest",
            start_time=end_time - timedelta(hours=5),
            end_time=end_time,
            duration_in_secs=5 * 60 * 60,
            url=f"{resource.url}{self.statistic_index}",
            host=resource.host,
            key=str(self.statistic_index),
            info={"fields": ["medal"]} if medal else {},
        )
        account = account or Account.objects.create(resource=resource, key=f"user-{self.statistic_index}")
        return Statistics.objects.create(
            resource=resource,
            contest=contest,
            account=account,
            place=str(place) if place is not None else None,
            place_as_int=place,
            medal=medal,
            addition=addition or {},
        )

    def recalculate(self, resource, **kwargs):
        call_command("set_resources_accounts", resources=[resource.host], stdout=StringIO(), **kwargs)
        resource.refresh_from_db()

    def initialize(self, **kwargs):
        output = StringIO()
        call_command("set_resources_accounts", initialize_medal_win_gold=True, stdout=output, **kwargs)
        return output.getvalue()

    def test_standard_medal_contributions_determine_equivalence(self):
        for medal, place, expected in (
            ("gold", 1, None),
            ("gold", 2, False),
            ("gold", None, False),
            ("silver", 1, False),
            ("silver", 2, None),
            ("bronze", 3, None),
        ):
            with self.subTest(medal=medal, place=place):
                resource = self.create_resource()
                self.create_statistic(resource, place=place, medal=medal)
                self.recalculate(resource)
                assert resource.medal_win_equals_gold is expected

    def test_equal_totals_do_not_hide_contradictory_results(self):
        resource = self.create_resource()
        statistic = self.create_statistic(resource, medal="silver")
        self.create_statistic(resource, place=2, account=statistic.account)

        self.recalculate(resource)

        statistic.account.refresh_from_db()
        assert statistic.account.n_win == statistic.account.n_gold == 1
        assert resource.medal_win_equals_gold is False

    def test_automatic_mode_detects_later_difference_and_requires_manual_reset(self):
        resource = self.create_resource()
        self.create_statistic(resource)
        self.recalculate(resource)
        assert resource.medal_win_equals_gold is None

        statistic = self.create_statistic(resource, place=2)
        self.recalculate(resource)
        assert resource.medal_win_equals_gold is False

        statistic.place = "1"
        statistic.place_as_int = 1
        statistic.save(update_fields=["place", "place_as_int"])
        self.recalculate(resource)
        assert resource.medal_win_equals_gold is False

        resource.medal_win_equals_gold = None
        resource.save(update_fields=["medal_win_equals_gold"])
        self.recalculate(resource)
        assert resource.medal_win_equals_gold is None

        self.create_statistic(resource, medal="silver")
        self.recalculate(resource)
        assert resource.medal_win_equals_gold is False

    def test_explicit_states_are_preserved(self):
        for flag, place in ((True, 2), (False, 1)):
            with self.subTest(flag=flag):
                resource = self.create_resource(medal_win_equals_gold=flag)
                self.create_statistic(resource, place=place)
                self.recalculate(resource)
                assert resource.medal_win_equals_gold is flag

    def test_empty_results_keep_automatic_mode(self):
        resource = self.create_resource()
        self.recalculate(resource)
        assert resource.medal_win_equals_gold is None

    def test_unconfigured_custom_medal_count_is_ignored(self):
        resource = self.create_resource()
        self.create_statistic(resource, addition={"n_gold": 100})
        self.recalculate(resource)
        assert resource.medal_win_equals_gold is None

    def test_concurrent_explicit_setting_is_preserved(self):
        resource = self.create_resource()
        Resource.objects.filter(pk=resource.pk).update(medal_win_equals_gold=True)

        assert not update_medal_win_equals_gold(resource, {"n_gold": 1})
        assert resource.medal_win_equals_gold is True
        resource.refresh_from_db()
        assert resource.medal_win_equals_gold is True

    def test_restricted_recalculation_detects_only_selected_accounts(self):
        for option in ("with_coders", "with_list_values"):
            with self.subTest(option=option):
                resource = self.create_resource()
                equal = self.create_statistic(resource).account
                different = self.create_statistic(resource, place=2).account
                coder = Coder.objects.create(username=option)
                if option == "with_coders":
                    equal.coders.add(coder)
                else:
                    coder_list = CoderList.objects.create(name="Medals", owner=coder)
                    group = ListGroup.objects.create(coder_list=coder_list)
                    ListValue.objects.create(coder_list=coder_list, group=group, account=equal)

                self.recalculate(resource, **{option: True})
                assert resource.medal_win_equals_gold is None

                if option == "with_coders":
                    different.coders.add(coder)
                else:
                    ListValue.objects.create(coder_list=coder_list, group=group, account=different)
                self.recalculate(resource, **{option: True})
                assert resource.medal_win_equals_gold is False

    def test_initialization_includes_disabled_resources_and_changes_only_flag(self):
        resource = self.create_resource(enable=False, has_statistic_medal=None, n_accounts=0)
        statistic = self.create_statistic(resource, place=2)
        country = CountryAccount.objects.create(resource=resource, country="PL", n_gold=7, n_medals=7)
        snapshots = [
            model.objects.values().get(pk=instance.pk)
            for model, instance in (
                (Resource, resource),
                (Statistics, statistic),
                (Account, statistic.account),
                (CountryAccount, country),
            )
        ]

        assert "Checked 1 resources; downgraded 1." in self.initialize()

        for (model, instance), before in zip(
            ((Resource, resource), (Statistics, statistic), (Account, statistic.account), (CountryAccount, country)),
            snapshots,
        ):
            after = model.objects.values().get(pk=instance.pk)
            if model is Resource:
                assert after.pop("medal_win_equals_gold") is False
                before.pop("medal_win_equals_gold")
            assert after == before

        assert "Checked 0 resources; downgraded 0." in self.initialize()

    def test_initialization_preserves_equal_empty_and_explicit_states(self):
        equal = self.create_resource()
        self.create_statistic(equal)
        empty = self.create_resource()
        for flag in (True, False):
            resource = self.create_resource(medal_win_equals_gold=flag)
            self.create_statistic(resource, place=2)

        assert "Checked 2 resources; downgraded 0." in self.initialize()

        equal.refresh_from_db()
        empty.refresh_from_db()
        assert equal.medal_win_equals_gold is None
        assert empty.medal_win_equals_gold is None
        assert set(
            Resource.objects.exclude(pk__in=[equal.pk, empty.pk]).values_list("medal_win_equals_gold", flat=True)
        ) == {True, False}

    def test_initialization_honors_resource_selection(self):
        selected = self.create_resource()
        other = self.create_resource()
        for resource in (selected, other):
            self.create_statistic(resource, place=2)

        self.initialize(resources=[str(selected.pk)])

        selected.refresh_from_db()
        other.refresh_from_db()
        assert selected.medal_win_equals_gold is False
        assert other.medal_win_equals_gold is None

    def test_initialization_includes_medal_metadata_and_unknown_contest_flags(self):
        for flag, info in ((False, {"fields": ["medal"]}), (None, {})):
            with self.subTest(flag=flag):
                resource = self.create_resource()
                statistic = self.create_statistic(resource, place=2)
                Contest.objects.filter(pk=statistic.contest_id).update(with_medals=flag, info=info)

                self.initialize(resources=[resource.host])

                resource.refresh_from_db()
                assert resource.medal_win_equals_gold is False

    def test_initialization_uses_custom_medals_for_the_configured_type(self):
        resource = self.create_resource(accounts_fields={"medal_fields": {"member": {"n_gold": "awards.gold"}}})
        self.create_statistic(resource, addition={"awards": {"gold": 100}})
        self.initialize()
        resource.refresh_from_db()
        assert resource.medal_win_equals_gold is None

        member = Account.objects.create(resource=resource, key="member", account_type=AccountType.MEMBER)
        self.create_statistic(resource, medal=None, account=member, addition={"awards": {"gold": 2}})
        self.initialize()
        resource.refresh_from_db()
        assert resource.medal_win_equals_gold is False

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

        resource.refresh_from_db()
        assert resource.medal_win_equals_gold is False

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
