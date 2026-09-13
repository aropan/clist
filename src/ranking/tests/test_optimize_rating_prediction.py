import math
import random
from copy import deepcopy
from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from clist.models import Contest, Resource
from ranking.management.commands.calculate_rating_prediction import (
    calculate_elo_mmr_replay,
    get_elo_mmr_rated_contests,
)
from ranking.management.commands.optimize_rating_prediction import Command as OptimizeRatingPredictionCommand
from ranking.management.commands.optimize_rating_prediction import (
    OptimizationParameters,
    calculate_contest_prediction_metrics,
    evaluate_elo_mmr_parameters,
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
    def create_resource(**overrides):
        rating_prediction = {
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
        }
        rating_prediction.update(overrides)
        return Resource.objects.create(
            host="optimize-rating.example.com",
            url="https://optimize-rating.example.com/",
            enable=True,
            rating_prediction=rating_prediction,
        )

    @staticmethod
    def absent_participant_decay():
        return {
            "score_method": "icpc_itmo_rating",
            "score_scale": 200,
            "decay_multiplier": 0.7,
            "maximum_missed_contests": 7,
        }

    @staticmethod
    def create_contest(resource, index, rows):
        end_time = timezone.now() - timedelta(days=20 - index)
        contest = Contest.objects.create(
            resource=resource,
            title=f"Contest {index}",
            start_time=end_time - timedelta(hours=5),
            end_time=end_time,
            duration_in_secs=None,
            url=f"https://optimize-rating.example.com/custom-{index}",
            host=resource.host,
            key=f"custom-{index}",
            n_statistics=len(rows),
        )
        for account, place, solving in rows:
            Statistics.objects.create(
                resource=resource,
                contest=contest,
                account=account,
                place=str(place),
                place_as_int=place,
                solving=solving,
            )
        return contest

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

    def test_optimizer_uses_competitive_ratings_independently_of_account_decay(self):
        resource = self.create_resource()
        resource.rating_prediction.update(rating_decay=50, sig_noob=350)
        accounts, contests = self.create_history(resource, n_contests=4)
        third = Account.objects.create(resource=resource, key="third")
        for contest in contests:
            Statistics.objects.create(resource=resource, contest=contest, account=third, place="3", place_as_int=3)
        Statistics.objects.filter(account=accounts[0], contest__in=contests[1:3]).update(skip_in_stats=True)
        rated_contests = get_elo_mmr_rated_contests(resource, timezone.now())
        parameters = OptimizationParameters(weight_limit=0.3, sig_limit=80, sig_noob=350, annual_drift=0)

        predicted_ratings = []
        for rating_decay in (50, 2000):
            resource.rating_prediction["rating_decay"] = rating_decay
            with mock.patch(
                "ranking.management.commands.optimize_rating_prediction.calculate_contest_prediction_metrics",
                wraps=calculate_contest_prediction_metrics,
            ) as metrics:
                evaluate_elo_mmr_parameters(rated_contests, resource.rating_prediction, parameters)

            replay = calculate_elo_mmr_replay(resource, timezone.now())
            for snapshot, call in zip(replay.snapshots, metrics.call_args_list):
                ratings = call.args[3]
                for ranking in snapshot.rankings:
                    assert ranking["prediction"]["old_rating"] == round(ratings[str(ranking["account_id"])])
            first_rating = replay.snapshots[0].rankings[0]["prediction"]["new_rating"]
            predicted_rating = round(metrics.call_args_list[-1].args[3][str(accounts[0].pk)])
            assert predicted_rating == first_rating
            predicted_ratings.append(predicted_rating)
        assert predicted_ratings[0] == predicted_ratings[1]

    def test_absent_decay_optimizer_scores_previous_final_intersection_and_replays_full_events(self):
        resource = self.create_resource(absent_participant_decay=self.absent_participant_decay())
        accounts = {
            key: Account.objects.create(resource=resource, key=key) for key in ("first", "second", "third", "fourth")
        }
        self.create_contest(
            resource,
            0,
            [
                (accounts["first"], 1, 10),
                (accounts["second"], 2, 5),
                (accounts["third"], 3, 2),
            ],
        )
        self.create_contest(
            resource,
            1,
            [
                (accounts["first"], 1, 10),
                (accounts["second"], 1, 10),
                (accounts["fourth"], 3, 1),
            ],
        )
        self.create_contest(
            resource,
            2,
            [
                (accounts["first"], 1, 10),
                (accounts["third"], 2, 5),
                (accounts["fourth"], 3, 1),
            ],
        )
        rated_contests = get_elo_mmr_rated_contests(resource, timezone.now())
        parameters = OptimizationParameters(weight_limit=0.3, sig_limit=80, sig_noob=350, annual_drift=0)

        assert str(accounts["third"].pk) in rated_contests[1].synthetic_participants
        assert str(accounts["second"].pk) in rated_contests[2].synthetic_participants
        with mock.patch(
            "ranking.management.commands.optimize_rating_prediction.calculate_contest_prediction_metrics",
            wraps=calculate_contest_prediction_metrics,
        ) as calculate_metrics:
            metrics = evaluate_elo_mmr_parameters(rated_contests, resource.rating_prediction, parameters)

        assert [metric.contest_index for metric in metrics] == [1, 2]
        first_metric_standings = calculate_metrics.call_args_list[0].args[2]
        second_metric_standings = calculate_metrics.call_args_list[1].args[2]
        assert first_metric_standings == [
            (str(accounts["first"].pk), 0, 1),
            (str(accounts["second"].pk), 0, 1),
        ]
        assert second_metric_standings == [
            (str(accounts["first"].pk), 0, 0),
            (str(accounts["fourth"].pk), 1, 1),
        ]

        result = OptimizeRatingPredictionCommand.evaluate_candidate(
            rated_contests,
            resource.rating_prediction,
            parameters,
            train_start=1,
            train_stop=2,
            half_life=8,
        )
        assert result.train.log_loss == metrics[0].log_loss
        assert result.test.log_loss == metrics[1].log_loss

        replay = calculate_elo_mmr_replay(resource, timezone.now())
        for metric_call, snapshot in zip(calculate_metrics.call_args_list, replay.snapshots[1:]):
            metric_ratings = metric_call.args[3]
            snapshot_rankings = {str(row["account_id"]): row for row in snapshot.rankings}
            for participant in metric_ratings:
                assert snapshot_rankings[participant]["prediction"]["old_rating"] == round(metric_ratings[participant])
        absent_prediction = replay.final[str(accounts["second"].pk)]["prediction"]
        assert absent_prediction["new_rating"] <= absent_prediction["old_rating"]

    def test_absent_decay_optimizer_rejects_windows_without_returning_participants(self):
        resource = self.create_resource(absent_participant_decay=self.absent_participant_decay())
        for contest_index in range(7):
            accounts = [
                Account.objects.create(resource=resource, key=f"user-{contest_index}-{index}") for index in range(2)
            ]
            self.create_contest(
                resource,
                contest_index,
                [
                    (accounts[0], 1, 2),
                    (accounts[1], 2, 1),
                ],
            )

        with self.assertRaisesMessage(CommandError, "no contest metrics selected"):
            call_command(
                "optimize_rating_prediction",
                resources=[resource.host],
                trials=1,
                burn_in_contests=1,
                test_contests=2,
                stdout=StringIO(),
            )

    def test_default_optimizer_candidate_count_is_current_plus_300_trials(self):
        parser = OptimizeRatingPredictionCommand().create_parser("manage.py", "optimize_rating_prediction")

        args = parser.parse_args(["--resources", "example.com"])

        assert args.trials == 300

    def test_recommended_parameters_use_resource_override_precision(self):
        parameters = OptimizationParameters(
            weight_limit=0.456,
            sig_limit=73.14,
            sig_noob=123.66,
            annual_drift=math.sqrt(0.436 * 365),
        ).rounded()

        assert parameters.weight_limit == pytest.approx(0.46)
        assert parameters.sig_limit == pytest.approx(73.1)
        assert parameters.sig_noob == pytest.approx(123.7)
        assert parameters.drift_per_day == pytest.approx(0.44)

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
        assert "Candidate configurations: 3" in output.getvalue()
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
