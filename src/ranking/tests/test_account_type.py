from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from clist.models import Resource
from ranking.enums import AccountType
from ranking.models import Account


class AccountTypeCounterTest(TestCase):
    @staticmethod
    def data_queries(queries):
        return [query for query in queries if not query["sql"].lstrip().upper().startswith("EXPLAIN")]

    @staticmethod
    def create_resource():
        resource = Resource(host="deferred-account-type.example.com", enable=True)
        Resource.objects.bulk_create([resource])
        return resource

    def test_deferred_account_type_does_not_add_queries_when_loading(self):
        resource = self.create_resource()
        Account.objects.bulk_create([Account(resource=resource, key=str(index)) for index in range(3)])

        with CaptureQueriesContext(connection) as queries:
            accounts = list(Account.objects.filter(resource=resource).only("pk"))

        queries = self.data_queries(queries)
        assert len(queries) == 1, queries
        assert len(accounts) == 3
        assert all("account_type" in account.get_deferred_fields() for account in accounts)

    def test_saving_another_field_does_not_load_deferred_account_type(self):
        resource = self.create_resource()
        account = Account.objects.create(resource=resource, key="member", account_type=AccountType.MEMBER)
        account = Account.objects.only("resource_id", "info", "name").get(pk=account.pk)
        account.name = "Updated name"

        with CaptureQueriesContext(connection) as queries:
            account.save(update_fields=["name"])

        queries = self.data_queries(queries)
        assert len(queries) == 1, queries
        assert "account_type" in account.get_deferred_fields()
        resource.refresh_from_db()
        assert resource.n_member_accounts == 1

    def test_counter_follows_explicit_change_to_deferred_account_type(self):
        resource = self.create_resource()
        account = Account.objects.create(resource=resource, key="member", account_type=AccountType.MEMBER)
        account = Account.objects.only("resource_id", "info").get(pk=account.pk)
        account.account_type = AccountType.TEAM

        account.save(update_fields=["account_type"])
        account.save(update_fields=["account_type"])

        resource.refresh_from_db()
        assert resource.n_accounts == 1
        assert resource.n_member_accounts == 0
        assert resource.n_team_accounts == 1

    def test_counter_follows_info_change_with_deferred_account_type(self):
        resource = self.create_resource()
        account = Account.objects.create(resource=resource, key="member", account_type=AccountType.MEMBER)
        account = Account.objects.only("resource_id", "info").get(pk=account.pk)
        account.info["is_team"] = True

        account.save(update_fields=["info"])

        resource.refresh_from_db()
        assert account.account_type == AccountType.TEAM
        assert resource.n_accounts == 1
        assert resource.n_member_accounts == 0
        assert resource.n_team_accounts == 1

    def test_counter_decrements_when_deleting_account_with_deferred_type(self):
        resource = self.create_resource()
        account = Account.objects.create(resource=resource, key="member", account_type=AccountType.MEMBER)
        account = Account.objects.only("resource_id").get(pk=account.pk)

        account.delete()

        resource.refresh_from_db()
        assert resource.n_accounts == 0
        assert resource.n_member_accounts == 0

    def test_counter_follows_account_type_changes(self):
        resource = Resource.objects.create(
            host="account-type.example.com",
            enable=True,
            url="https://account-type.example.com/",
        )
        account = Account.objects.create(resource=resource, key="member")

        account.account_type = AccountType.MEMBER
        account.save(update_fields=["name"])
        account.refresh_from_db()
        resource.refresh_from_db()
        assert account.account_type == AccountType.USER
        assert resource.n_member_accounts is None

        account.info["is_member"] = True
        account.save(update_fields=["info"])

        resource.refresh_from_db()
        assert account.account_type == AccountType.MEMBER
        assert resource.n_accounts == 1
        assert resource.n_member_accounts == 1
        assert resource.has_account_types()

        account.save(update_fields=["name"])
        resource.refresh_from_db()
        assert resource.n_member_accounts == 1

        account.info.pop("is_member")
        account.info["is_team"] = True
        account.save(update_fields=["info"])

        resource.refresh_from_db()
        assert account.account_type == AccountType.TEAM
        assert resource.n_member_accounts == 0
        assert resource.n_team_accounts == 1

        account.delete()
        resource.refresh_from_db()
        assert resource.n_accounts == 0
        assert resource.n_team_accounts == 0
