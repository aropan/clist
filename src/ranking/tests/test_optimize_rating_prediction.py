import random
from copy import deepcopy
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from clist.models import Contest, Resource
from ranking.management.commands.optimize_rating_prediction import (
    calculate_contest_prediction_metrics,
    sample_parameters,
)
from ranking.models import Account, Statistics
from utils.attrdict import AttrDict


class OptimizeRatingPredictionTest(TestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(Resource, "update_icon")
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def create_resource():
        return Resource.objects.create(
            host="optimize-rating.example.com",
            url="https://optimize-rating.example.com/",
            enable=True,
            rating_prediction={
                "algorithm": "elo_mmr_py",
                "algorithm_version": "2.0.0",
                "save_rating": True,
                "system": "mmr",
                "initial_rating": 1500.0,
                "weight_limit": 0.3,
                "sig_limit": 80.0,
                "drift_per_day": 0.0,
                "noob_delay": [],
                "split_ties": False,
                "subsample_size": None,
                "subsample_bucket": 0.00001,
            },
        )

    @staticmethod
    def create_history(resource, n_contests=7):
        accounts = [
            Account.objects.create(resource=resource, key="first"),
            Account.objects.create(resource=resource, key="second"),
        ]
        now = timezone.now()
        contests = []
        for index in range(n_contests):
            end_time = now - timedelta(days=n_contests - index)
            contest = Contest.objects.create(
                resource=resource,
                title=f"Contest {index + 1}",
                start_time=end_time - timedelta(hours=5),
                end_time=end_time,
                duration_in_secs=None,
                url=f"https://optimize-rating.example.com/{index + 1}",
                host=resource.host,
                key=str(index + 1),
                n_statistics=2,
            )
            places = (1, 2) if index % 2 == 0 else (2, 1)
            for account, place in zip(accounts, places):
                Statistics.objects.create(
                    resource=resource,
                    contest=contest,
                    account=account,
                    place=str(place),
                    place_as_int=place,
                )
            contests.append(contest)
        return accounts, contests

    def test_prediction_metrics_use_rating_and_rank_distance(self):
        standings = [("first", 0, 0), ("second", 1, 1)]

        correct = calculate_contest_prediction_metrics(0, None, standings, {"first": 2000, "second": 1000})
        equal = calculate_contest_prediction_metrics(0, None, standings, {"first": 1500, "second": 1500})
        wrong = calculate_contest_prediction_metrics(0, None, standings, {"first": 1000, "second": 2000})

        assert correct.log_loss < equal.log_loss < wrong.log_loss
        assert correct.rank_rmse < equal.rank_rmse < wrong.rank_rmse

    def test_small_annual_drift_range_is_respected(self):
        ranges = AttrDict({
            "weight_limit": (0.1, 1.0),
            "sig_limit": (20.0, 100.0),
            "sig_noob": (100.0, 500.0),
            "annual_drift": (0.0, 0.5),
        })

        randomizer = random.Random(42)
        samples = [sample_parameters(randomizer, ranges).annual_drift for _ in range(100)]

        assert all(0.0 <= sample <= 0.5 for sample in samples)
        assert any(not sample for sample in samples)
        assert any(sample > 0.0 for sample in samples)

    def test_positive_annual_drift_range_below_one_is_respected(self):
        ranges = AttrDict({
            "weight_limit": (0.1, 1.0),
            "sig_limit": (20.0, 100.0),
            "sig_noob": (100.0, 500.0),
            "annual_drift": (0.1, 0.5),
        })

        randomizer = random.Random(42)
        samples = [sample_parameters(randomizer, ranges).annual_drift for _ in range(2000)]

        assert 0.1 <= min(samples) < max(samples) <= 0.5

    def test_command_runs_walk_forward_without_database_writes(self):
        resource = self.create_resource()
        _, contests = self.create_history(resource)
        rating_prediction = deepcopy(resource.rating_prediction)

        output = StringIO()
        call_command(
            "optimize_rating_prediction",
            resources=[resource.host],
            trials=2,
            burn_in_contests=1,
            test_contests=2,
            top=2,
            stdout=output,
        )

        resource.refresh_from_db()
        assert resource.rating_prediction == rating_prediction
        assert not Statistics.objects.filter(contest__in=contests, rating_prediction__isnull=False).exists()
        assert "Current" in output.getvalue()
        assert "Optimized" in output.getvalue()
        assert "Suggested Resource.rating_prediction override" in output.getvalue()

    def test_command_rejects_contests_above_participant_limit(self):
        resource = self.create_resource()
        _, contests = self.create_history(resource)
        third = Account.objects.create(resource=resource, key="third")
        for contest in contests:
            Statistics.objects.create(
                resource=resource,
                contest=contest,
                account=third,
                place="3",
                place_as_int=3,
            )
            contest.n_statistics = 3
            contest.save(update_fields=["n_statistics"])

        with self.assertRaisesMessage(CommandError, "exceeding --max-participants=2"):
            call_command(
                "optimize_rating_prediction",
                resources=[resource.host],
                trials=1,
                burn_in_contests=1,
                test_contests=2,
                max_participants=2,
                stdout=StringIO(),
            )
