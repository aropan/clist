import pytest
from django.test import TestCase

from clist.models import Resource
from ranking.models import Account, AccountRenaming
from ranking.utils import rename_account


class RenameAccountVerificationTest(TestCase):
    def test_verification_requirement_is_preserved_from_either_account(self):
        resource = Resource(host="rename-verification.example", url="https://rename-verification.example/", enable=True)
        Resource.objects.bulk_create([resource])

        for index, (old_required, new_required) in enumerate((
            (True, False),
            (False, True),
            (True, True),
            (False, False),
        )):
            with self.subTest(old_required=old_required, new_required=new_required):
                old = Account.objects.create(resource=resource, key=f"old-{index}", need_verification=old_required)
                new = Account.objects.create(resource=resource, key=f"new-{index}", need_verification=new_required)

                account = rename_account(old, new)

                account.refresh_from_db()
                assert account.need_verification == (old_required or new_required)
                assert not Account.objects.filter(resource=resource, key=f"old-{index}").exists()
                assert resource.accountrenaming_set.get(old_key=f"old-{index}").new_key == account.key


class RenameAccountStateTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.resource = Resource(host="rename-state.example", enable=True)
        Resource.objects.bulk_create([cls.resource])

    def test_deleted_source_does_not_change_target_state_or_rating(self):
        for index, deleted in enumerate((None, False)):
            with self.subTest(deleted=deleted):
                old = Account.objects.create(resource=self.resource, key=f"old-{index}", deleted=True)
                new = Account.objects.create(
                    resource=self.resource,
                    key=f"new-{index}",
                    deleted=deleted,
                    rating=1900,
                    rating50=38,
                    resource_rank=7,
                )

                account = rename_account(old, new)

                account.refresh_from_db()
                assert account.deleted is deleted
                assert (account.rating, account.rating50, account.resource_rank) == (1900, 38, 7)

    def test_source_duplicate_is_not_inherited_but_profile_fields_are(self):
        other = Account.objects.create(resource=self.resource, key="other")
        for index, duplicate_is_target in enumerate((True, False)):
            with self.subTest(duplicate_is_target=duplicate_is_target):
                new = Account.objects.create(resource=self.resource, key=f"new-{index}")
                old = Account.objects.create(
                    resource=self.resource,
                    key=f"old-{index}",
                    name="Original name",
                    duplicate=new if duplicate_is_target else other,
                )

                account = rename_account(old, new)

                account.refresh_from_db()
                assert account.duplicate_id is None
                assert account.get_current() == account
                assert account.name == "Original name"
                assert Account.objects.filter(pk=other.pk).exists()

    def test_existing_target_duplicate_is_preserved(self):
        canonical = Account.objects.create(resource=self.resource, key="canonical")
        old = Account.objects.create(resource=self.resource, key="old")
        new = Account.objects.create(resource=self.resource, key="new", duplicate=canonical)

        account = rename_account(old, new)

        account.refresh_from_db()
        assert account.duplicate_id == canonical.pk
        assert account.get_current() == canonical

    def test_target_duplicate_chain_through_source_survives_the_merge(self):
        for index, (indirect, has_canonical) in enumerate(((False, False), (True, False), (False, True), (True, True))):
            with self.subTest(indirect=indirect, has_canonical=has_canonical):
                canonical = (
                    Account.objects.create(resource=self.resource, key=f"canonical-{index}") if has_canonical else None
                )
                old = Account.objects.create(resource=self.resource, key=f"old-{index}", duplicate=canonical)
                alias = Account.objects.create(resource=self.resource, key=f"alias-{index}", duplicate=old)
                new = Account.objects.create(
                    resource=self.resource, key=f"new-{index}", duplicate=alias if indirect else old
                )

                account = rename_account(old, new)

                account.refresh_from_db()
                alias.refresh_from_db()
                assert account.get_current() == (canonical or account)
                assert alias.duplicate_id == account.pk
                assert alias.get_current() == (canonical or account)


class AccountLookupTest(TestCase):
    def setUp(self):
        self.resource = Resource(host="account-lookup.example", url="https://account-lookup.example/", enable=True)
        Resource.objects.bulk_create([self.resource])
        self.account = Account.objects.create(resource=self.resource, key="Canonical")

    def test_single_and_bulk_lookups_resolve_historical_keys(self):
        AccountRenaming.objects.create(resource=self.resource, old_key="Original", new_key=self.account.key)

        assert Account.get(self.resource, "Original") == self.account
        assert Account.get_many(self.resource, ["Original", self.account.key, "missing"]) == {
            "Original": self.account,
            self.account.key: self.account,
        }

    def test_existing_account_takes_precedence_over_a_historical_key(self):
        other = Account.objects.create(resource=self.resource, key="Other")
        AccountRenaming.objects.create(resource=self.resource, old_key=self.account.key, new_key=other.key)

        assert Account.get(self.resource, self.account.key) == self.account

    def test_case_insensitive_lookup_is_optional_and_preserves_requested_keys(self):
        AccountRenaming.objects.create(resource=self.resource, old_key="Original", new_key="CANONICAL")

        assert Account.get(self.resource, "canonical") is None
        assert Account.get_many(self.resource, ["ORIGINAL", "canonical"], ignore_case=True) == {
            "ORIGINAL": self.account,
            "canonical": self.account,
        }

    def test_case_insensitive_lookup_prefers_exact_keys_and_rejects_ambiguity(self):
        lower = Account.objects.create(resource=self.resource, key="canonical")

        assert Account.get_many(self.resource, ["Canonical", "canonical", "CANONICAL"], ignore_case=True) == {
            "Canonical": self.account,
            "canonical": lower,
        }

    def test_case_insensitive_lookup_uses_database_casing_for_unicode_keys(self):
        account = Account.objects.create(resource=self.resource, key="straße")
        AccountRenaming.objects.create(resource=self.resource, old_key="Früher", new_key="STRAßE")

        assert Account.get_many(self.resource, ["Straße", "FRÜHER", "straße"], ignore_case=True) == {
            "Straße": account,
            "FRÜHER": account,
            "straße": account,
        }

    def test_renamings_are_scoped_to_the_resource_and_missing_targets_are_ignored(self):
        other_resource = Resource(host="other-account-lookup.example", enable=True)
        Resource.objects.bulk_create([other_resource])
        AccountRenaming.objects.create(resource=other_resource, old_key="foreign", new_key=self.account.key)
        AccountRenaming.objects.create(resource=self.resource, old_key="deleted", new_key=None)
        AccountRenaming.objects.create(resource=self.resource, old_key="dangling", new_key="missing")

        assert Account.get_many(self.resource, ["foreign", "deleted", "dangling"]) == {}
        assert Account.get(self.resource, "dangling") is None

    def test_bulk_lookup_uses_a_fixed_number_of_queries(self):
        keys = [f"original-{index}" for index in range(10)]
        AccountRenaming.objects.bulk_create([
            AccountRenaming(resource=self.resource, old_key=key, new_key=self.account.key) for key in keys
        ])

        with self.assertNumQueries(2):
            result = Account.get_many(self.resource, keys)

        assert result == dict.fromkeys(keys, self.account)
        with self.assertNumQueries(0):
            assert Account.get_many(self.resource, []) == {}

    def test_current_account_follows_duplicate_links(self):
        alias = Account.objects.create(resource=self.resource, key="alias", duplicate=self.account)
        older = Account.objects.create(resource=self.resource, key="older", duplicate=alias)

        assert self.account.get_current() == self.account
        assert Account.get(self.resource, older.key).get_current() == self.account

    def test_current_account_rejects_duplicate_cycles(self):
        alias = Account.objects.create(resource=self.resource, key="alias", duplicate=self.account)
        self.account.duplicate = alias
        self.account.save(update_fields=["duplicate"])

        with pytest.raises(ValueError, match="Cyclic account duplicates"):
            self.account.get_current()
