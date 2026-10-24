from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils.timezone import now

from clist.models import Contest, Resource
from ranking.models import Account, Statistics


class StatisticsAccountCountersTest(TestCase):
    def setUp(self):
        with mock.patch.object(Resource, "update_icon"):
            self.resource = Resource.objects.create(
                host="statistics.example", url="https://statistics.example/", enable=True
            )
        self.account = Account.objects.create(resource=self.resource, key="coder")
        self.contests = [
            Contest.objects.create(
                resource=self.resource,
                key=str(index),
                title=f"Contest {index}",
                url=f"https://statistics.example/{index}",
                start_time=now() - timedelta(days=2),
                end_time=now() - timedelta(days=1),
            )
            for index in range(2)
        ]

    def create_statistic(self, contest, **kwargs):
        return Statistics.objects.create(
            resource=self.resource, account=self.account, contest=contest, skip_in_stats=True, **kwargs
        )

    def test_cached_statistics_with_separate_accounts_keep_all_contributions(self):
        for contest in self.contests:
            self.create_statistic(contest)
        first, second = Statistics.objects.select_related("account").order_by("contest_id")

        for count, (statistic, short) in enumerate(((first, "A"), (second, "A"), (first, "B")), 1):
            statistic.addition.setdefault("problems", {})[short] = {"upsolving": {"result": "+"}}
            statistic.save(update_fields=["addition"])
            self.account.refresh_from_db()
            assert self.account.n_upsolved == count
            assert self.account.total_solving == count
            assert statistic.account.n_upsolved == count

    def test_repeated_saves_and_delete_use_last_saved_scores(self):
        statistic = self.create_statistic(
            self.contests[0],
            solving=200,
            addition={
                "problems": {"A": {"result": 200, "partial": True, "upsolving": {"result": 300, "partial": True}}}
            },
        )
        self.account.info["unsaved"] = True
        for score in (500, 500, 400):
            statistic.addition["problems"]["A"]["upsolving"] = {"result": score, "partial": score < 500}
            statistic.save(update_fields=["addition"])
            account = Account.objects.get(pk=self.account.pk)
            assert account.total_solving == score
            assert account.upsolving == score - 200
            assert account.n_upsolved == (score == 500)
            assert statistic.account.total_solving == score
            assert self.account.info["unsaved"] is True

        statistic.delete()

        self.account.refresh_from_db()
        assert self.account.total_solving == 0
        assert self.account.upsolving == 0
        assert self.account.n_upsolved == 0
