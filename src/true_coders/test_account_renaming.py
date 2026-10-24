from datetime import timedelta
from unittest import mock

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import AnonymousUser, Permission, User
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from clist.models import Contest, Resource
from clist.tests import MIDDLEWARE_WITHOUT_DEBUG_TOOLING
from notification.models import Subscription
from ranking.models import Account, AccountRenaming, Statistics
from ranking.utils import rename_account
from true_coders.models import Coder, CoderList, ListGroup, ListValue
from true_coders.views import MAX_ACCOUNTS_TO_RENAME, rename_accounts


@override_settings(MIDDLEWARE=MIDDLEWARE_WITHOUT_DEBUG_TOOLING)
class AccountRenamingViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username="account-renaming-staff", is_staff=True)
        cls.editor = User.objects.create_user(username="account-renaming-editor")
        cls.regular = User.objects.create_user(username="account-renaming-regular")
        cls.editor.user_permissions.add(
            Permission.objects.get(content_type__app_label="ranking", codename="change_accountrenaming")
        )
        for user in (cls.staff, cls.editor, cls.regular):
            Coder.objects.create(user=user, username=user.username)
        cls.resource = Resource(host="account-renaming.example", enable=True)
        cls.other_resource = Resource(host="other-account-renaming.example", enable=True)
        Resource.objects.bulk_create([cls.resource, cls.other_resource])
        cls.target = Account.objects.create(resource=cls.resource, key="kept-account", name="Kept name")
        cls.first = Account.objects.create(resource=cls.resource, key="old-first", need_verification=True)
        cls.second = Account.objects.create(resource=cls.resource, key="old-second")
        cls.foreign = Account.objects.create(resource=cls.other_resource, key="foreign")
        cls.url = reverse("coder:rename_accounts")

    def post(self, user=None, **data):
        payload = {"accounts": [self.first.pk, self.second.pk, self.target.pk], "target": self.target.pk}
        payload.update(data)
        request = RequestFactory().post(self.url, payload)
        request.user = self.staff if user is None else user
        return rename_accounts(request)

    def test_staff_can_merge_results_coders_and_historical_keys(self):
        self.first.coders.add(self.regular.coder)
        self.second.coders.add(self.editor.coder)
        AccountRenaming.objects.create(resource=self.resource, old_key="original-first", new_key=self.first.key)
        now = timezone.now()
        contests = []
        for index in range(3):
            contest = Contest.objects.create(
                resource=self.resource,
                title=f"Merge contest {index}",
                key=str(index),
                start_time=now - timedelta(hours=2),
                end_time=now - timedelta(hours=1),
                duration_in_secs=3600,
            )
            contests.append(contest)
        for account, contest, solving in (
            (self.target, contests[0], 10),
            (self.first, contests[0], 1),
            (self.first, contests[1], 2),
            (self.second, contests[2], 3),
        ):
            Statistics.objects.create(account=account, resource=self.resource, contest=contest, solving=solving)

        self.client.force_login(self.staff)
        response = self.client.post(
            self.url, {"accounts": [self.first.pk, self.target.pk, self.second.pk], "target": self.target.pk}
        )

        assert response.status_code == 200
        assert response.json()["target"] == self.target.pk
        assert not Account.objects.filter(pk__in=[self.first.pk, self.second.pk]).exists()
        self.target.refresh_from_db()
        assert self.target.key == "kept-account"
        assert self.target.name == "Kept name"
        assert self.target.need_verification
        assert set(self.target.coders.all()) == {self.regular.coder, self.editor.coder}
        assert dict(self.target.statistics_set.values_list("contest_id", "solving")) == {
            contests[0].pk: 10,
            contests[1].pk: 2,
            contests[2].pk: 3,
        }
        assert dict(AccountRenaming.objects.values_list("old_key", "new_key")) == dict.fromkeys(
            ["original-first", self.first.key, self.second.key], self.target.key
        )
        log = LogEntry.objects.get(user=self.staff, object_id=str(self.target.pk))
        assert log.action_flag == CHANGE
        assert self.first.key in log.change_message
        assert self.second.key in log.change_message

    def test_non_staff_with_renaming_permission_can_merge_into_any_selected_account(self):
        response = self.post(user=self.editor, target=self.second.pk)

        assert response.status_code == 200
        assert set(Account.objects.filter(resource=self.resource).values_list("pk", flat=True)) == {self.second.pk}
        assert AccountRenaming.objects.get(old_key=self.target.key).new_key == self.second.key

    def test_shared_list_entries_are_deduplicated_and_other_groups_are_preserved(self):
        coder_list = CoderList.objects.create(owner=self.staff.coder, name="Merge list")
        shared_group = ListGroup.objects.create(coder_list=coder_list)
        other_group = ListGroup.objects.create(coder_list=coder_list)
        kept = ListValue.objects.create(coder_list=coder_list, group=shared_group, account=self.target)
        for account in (self.first, self.second):
            ListValue.objects.create(coder_list=coder_list, group=shared_group, account=account)
        ListValue.objects.create(coder_list=coder_list, group=other_group, account=self.first)

        response = self.post()

        assert response.status_code == 200
        assert set(coder_list.values.values_list("group_id", "account_id")) == {
            (shared_group.pk, self.target.pk),
            (other_group.pk, self.target.pk),
        }
        assert ListValue.objects.filter(pk=kept.pk).exists()
        self.target.refresh_from_db()
        assert self.target.n_listvalues == 2

    def test_shared_subscriptions_and_writer_credits_are_counted_once(self):
        subscription = Subscription.objects.create(coder=self.staff.coder, method="email")
        subscription.accounts.add(self.first, self.second, self.target)
        now = timezone.now()
        contest = Contest.objects.create(
            resource=self.resource,
            title="Shared writer contest",
            key="shared-writer",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            duration_in_secs=3600,
        )
        contest.writers.add(self.first, self.second, self.target)

        assert self.post().status_code == 200

        self.target.refresh_from_db()
        assert self.target.n_subscribers == self.target.subscribers.count() == 1
        assert self.target.n_writers == self.target.writer_set.count() == 1
        subscription.accounts.remove(self.target)
        contest.writers.remove(self.target)
        self.target.refresh_from_db()
        assert self.target.n_subscribers == self.target.n_writers == 0

    def test_deleted_source_does_not_delete_target_or_reset_its_rating(self):
        Account.objects.filter(pk=self.first.pk).update(deleted=True)
        Account.objects.filter(pk=self.target.pk).update(rating=1900, rating50=38, resource_rank=7)

        response = self.post()

        assert response.status_code == 200
        self.target.refresh_from_db()
        assert self.target.deleted is None
        assert (self.target.rating, self.target.rating50, self.target.resource_rank) == (1900, 38, 7)
        assert not Account.objects.filter(pk__in=[self.first.pk, self.second.pk]).exists()

    def test_duplicate_sources_do_not_create_cycles_in_the_target(self):
        Account.objects.filter(pk=self.first.pk).update(duplicate=self.target)
        Account.objects.filter(pk=self.second.pk).update(duplicate=self.first)
        alias = Account.objects.create(resource=self.resource, key="unselected-alias", duplicate=self.second)

        response = self.post()

        assert response.status_code == 200
        self.target.refresh_from_db()
        alias.refresh_from_db()
        assert self.target.duplicate_id is None
        assert self.target.get_current() == self.target
        assert alias.duplicate_id == self.target.pk
        assert alias.get_current() == self.target
        assert not Account.objects.filter(pk__in=[self.first.pk, self.second.pk]).exists()

    def test_anonymous_regular_and_inactive_staff_are_forbidden(self):
        inactive = User(username="inactive", is_staff=True, is_active=False)
        for user in (AnonymousUser(), self.regular, inactive):
            with self.subTest(user=user):
                assert self.post(user=user).status_code == 403
        assert Account.objects.count() == 4
        assert not AccountRenaming.objects.exists()

    def test_account_edit_permission_alone_does_not_allow_renaming(self):
        self.regular.user_permissions.add(
            Permission.objects.get(content_type__app_label="ranking", codename="change_account")
        )

        assert self.post(user=self.regular).status_code == 403

    def test_invalid_selections_are_rejected_before_any_changes(self):
        cases = (
            {"accounts": []},
            {"accounts": [self.target.pk]},
            {"accounts": [self.target.pk, self.target.pk]},
            {"accounts": [self.first.pk, "invalid"]},
            {"accounts": [self.first.pk, 2**64]},
            {"accounts": [self.first.pk, -1]},
            {"accounts": [self.first.pk, self.target.pk, 2**31 - 1]},
            {"accounts": [self.first.pk, self.target.pk, self.foreign.pk]},
            {"accounts": list(range(MAX_ACCOUNTS_TO_RENAME + 1))},
            {"target": ""},
            {"target": "invalid"},
            {"target": self.foreign.pk},
            {"accounts": [self.first.pk, self.second.pk]},
        )
        for data in cases:
            with self.subTest(data=data):
                assert self.post(**data).status_code == 400
                assert Account.objects.count() == 4
                assert not AccountRenaming.objects.exists()

    def test_deleted_target_is_rejected(self):
        Account.objects.filter(pk=self.target.pk).update(deleted=True)

        assert self.post().status_code == 400
        assert Account.objects.count() == 4

    def test_duplicate_ids_do_not_repeat_a_merge(self):
        response = self.post(accounts=[self.first.pk, self.target.pk, self.first.pk])

        assert response.status_code == 200
        assert AccountRenaming.objects.count() == 1
        assert Account.objects.filter(pk=self.second.pk).exists()

    def test_failure_rolls_back_the_whole_batch(self):
        def merge_or_fail(source, target):
            if source.pk == self.second.pk:
                raise RuntimeError("Merge failed")
            return rename_account(source, target)

        with (
            mock.patch("true_coders.views.rename_account", side_effect=merge_or_fail),
            self.assertRaisesMessage(RuntimeError, "Merge failed"),
        ):
            self.post()

        assert Account.objects.count() == 4
        assert not AccountRenaming.objects.exists()
        assert not LogEntry.objects.exists()
        self.target.refresh_from_db()
        assert not self.target.need_verification

    def test_endpoint_requires_post_and_csrf(self):
        self.client.force_login(self.staff)
        assert self.client.get(self.url).status_code == 405
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)

        response = client.post(self.url, {"accounts": [self.first.pk, self.target.pk], "target": self.target.pk})

        assert response.status_code == 403
        assert Account.objects.count() == 4

        response = client.get(reverse("coder:accounts"))
        assert response.status_code == 200
        response = client.post(
            self.url,
            {"accounts": [self.first.pk, self.target.pk], "target": self.target.pk},
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        assert response.status_code == 200

    def test_selection_controls_follow_permissions_in_full_and_paginated_views(self):
        for user, allowed in ((None, False), (self.regular, False), (self.staff, True), (self.editor, True)):
            if user:
                self.client.force_login(user)
            else:
                self.client.logout()
            for ajax in (False, True):
                with self.subTest(user=user, ajax=ajax):
                    headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"} if ajax else {}
                    response = self.client.get(reverse("coder:accounts"), {"search": "old-"}, **headers)

                    assert response.status_code == 200
                    content = response.content.decode()
                    assert ('class="account-renaming-select"' in content) == allowed
                    assert ('id="account-renaming"' in content) == (allowed and not ajax)
                    assert ('id="account-renaming-toggle"' in content) == (allowed and not ajax)

    def test_account_keys_are_escaped_in_selection_attributes(self):
        self.first.key = '<img src=x onerror="alert(1)">'
        self.first.save(update_fields=["key"])
        self.client.force_login(self.staff)

        response = self.client.get(reverse("coder:accounts"))

        assert response.status_code == 200
        self.assertContains(response, 'data-key="&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"')
        self.assertNotContains(response, '<img src=x onerror="alert(1)">')
