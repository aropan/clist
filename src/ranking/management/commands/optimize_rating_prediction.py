#!/usr/bin/env python3

import json
import math
import random
import tempfile
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path

import elo_mmr_py
import numpy as np
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_print_sql import print_sql_decorator
from prettytable import PrettyTable

from clist.models import Resource
from ranking.management.commands.calculate_rating_prediction import (
    ELO_MMR_ALGORITHM,
    ELO_MMR_SYSTEM_SETTINGS,
    apply_elo_mmr_absent_rating_cap,
    apply_elo_mmr_rating_floor,
    get_elo_mmr_rated_contests,
    get_elo_mmr_settings,
)
from utils.attrdict import AttrDict

ELO_SCALE = 400.0
DAYS_PER_YEAR = 365.0
DEFAULT_MAX_PARTICIPANTS = 2000


@dataclass(frozen=True)
class OptimizationParameters:
    weight_limit: float
    sig_limit: float
    sig_noob: float
    annual_drift: float

    @property
    def drift_per_day(self):
        return self.annual_drift**2 / DAYS_PER_YEAR

    def rounded(self):
        drift_per_day = round(self.drift_per_day, 2)
        return OptimizationParameters(
            weight_limit=round(self.weight_limit, 2),
            sig_limit=round(self.sig_limit, 1),
            sig_noob=round(self.sig_noob, 1),
            annual_drift=math.sqrt(drift_per_day * DAYS_PER_YEAR),
        )


@dataclass(frozen=True)
class ContestPredictionMetrics:
    contest_index: int
    contest: object
    n_participants: int
    log_loss: float
    rank_rmse: float

    @property
    def predictability(self):
        return 1.0 - self.log_loss / math.log(2.0)


def calculate_contest_prediction_metrics(contest_index, contest, standings, ratings):
    n_participants = len(standings)
    if n_participants < 2:
        raise ValueError("at least two standings are required")

    rating_values = np.array([ratings[participant] for participant, _, _ in standings], dtype=np.float64)
    low_ranks = np.array([low_rank for _, low_rank, _ in standings], dtype=np.float64)
    high_ranks = np.array([high_rank for _, _, high_rank in standings], dtype=np.float64)

    logits = (rating_values[:, None] - rating_values[None, :]) * math.log(10.0) / ELO_SCALE
    win_probabilities = 1.0 / (1.0 + np.exp(-np.clip(logits, -50.0, 50.0)))

    rows, columns = np.triu_indices(n_participants, k=1)
    actual_outcomes = np.full(len(rows), 0.5, dtype=np.float64)
    actual_outcomes[high_ranks[rows] < low_ranks[columns]] = 1.0
    actual_outcomes[high_ranks[columns] < low_ranks[rows]] = 0.0
    pair_probabilities = np.clip(win_probabilities[rows, columns], 1e-15, 1.0 - 1e-15)
    log_loss = -np.mean(
        actual_outcomes * np.log(pair_probabilities) + (1.0 - actual_outcomes) * np.log(1.0 - pair_probabilities)
    )

    expected_ranks = 1.0 + np.sum(1.0 - win_probabilities, axis=1) - 0.5
    actual_ranks = 1.0 + (low_ranks + high_ranks) / 2.0
    normalized_errors = (expected_ranks - actual_ranks) / (n_participants - 1)
    rank_rmse = np.sqrt(np.mean(normalized_errors**2))

    return ContestPredictionMetrics(
        contest_index=contest_index,
        contest=contest,
        n_participants=n_participants,
        log_loss=float(log_loss),
        rank_rmse=float(rank_rmse),
    )


def aggregate_prediction_metrics(metrics, start, stop, half_life=None):
    selected = [metric for metric in metrics if start <= metric.contest_index < stop]
    if not selected:
        raise ValueError("no contest metrics selected")
    if half_life is None:
        weights = np.ones(len(selected), dtype=np.float64)
    else:
        ages = np.arange(len(selected) - 1, -1, -1, dtype=np.float64)
        weights = np.exp2(-ages / half_life)
    log_loss = float(np.average([metric.log_loss for metric in selected], weights=weights))
    rank_rmse = float(np.average([metric.rank_rmse for metric in selected], weights=weights))
    return AttrDict({
        "log_loss": log_loss,
        "predictability": 1.0 - log_loss / math.log(2.0),
        "rank_rmse": rank_rmse,
    })


def make_elo_mmr_system(config, parameters):
    system_kwargs = {field: config[field] for field in ELO_MMR_SYSTEM_SETTINGS}
    system_kwargs.update({
        "weight_limit": parameters.weight_limit,
        "sig_limit": parameters.sig_limit,
        "drift_per_day": parameters.drift_per_day,
    })
    return elo_mmr_py.EloMmrConfig(config["system"], **system_kwargs)


def get_contest_metric_standings(rated_contests, contest_index, use_previous_contest_participants):
    standings = rated_contests[contest_index].standings
    if not use_previous_contest_participants:
        return standings
    if not contest_index:
        return []

    previous_participants = set(rated_contests[contest_index - 1].participants)
    standings = [standing for standing in standings if standing[0] in previous_participants]
    normalized = []
    index = 0
    while index < len(standings):
        end = index + 1
        while end < len(standings) and standings[end][1:] == standings[index][1:]:
            end += 1
        for participant, _, _ in standings[index:end]:
            normalized.append((participant, index, end - 1))
        index = end
    return normalized


def evaluate_elo_mmr_parameters(rated_contests, config, parameters):
    system = make_elo_mmr_system(config, parameters)
    rater = elo_mmr_py.Rater(
        system,
        mu_noob=config["initial_rating"],
        sig_noob=parameters.sig_noob,
    )
    metrics = []
    absent_participant_decay = config.get("absent_participant_decay")
    apply_rating_floor = bool(config.get("rating_decay") or absent_participant_decay)
    with tempfile.TemporaryDirectory(prefix="clist-elo-mmr-optimize-") as temporary_directory:
        checkpoint_path = Path(temporary_directory) / "checkpoint.json"
        previous_players = {}
        for contest_index, rated_contest in enumerate(rated_contests):
            contest, _, _, native_contest = rated_contest
            standings = get_contest_metric_standings(
                rated_contests,
                contest_index,
                use_previous_contest_participants=bool(absent_participant_decay),
            )
            current_ratings = rater.ratings
            ratings = {
                participant: current_ratings[participant].mu
                if participant in current_ratings
                else config["initial_rating"]
                for participant, _, _ in standings
            }
            if len(standings) >= 2:
                metrics.append(calculate_contest_prediction_metrics(contest_index, contest, standings, ratings))
            rater.add(native_contest)
            if apply_rating_floor or rated_contest.synthetic_participants:
                rater.save(checkpoint_path)
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf8"))
                checkpoint_changed = False
                if rated_contest.synthetic_participants:
                    checkpoint_changed |= apply_elo_mmr_absent_rating_cap(
                        checkpoint,
                        previous_players,
                        rated_contest.synthetic_participants,
                    )
                if apply_rating_floor:
                    checkpoint_changed |= apply_elo_mmr_rating_floor(
                        checkpoint,
                        (participant for participant, _, _ in rated_contest.full_standings),
                    )
                if checkpoint_changed:
                    checkpoint_path.write_text(json.dumps(checkpoint, separators=(",", ":")), encoding="utf8")
                    rater = elo_mmr_py.Rater.load(checkpoint_path)
                previous_players = checkpoint["players"]
    return metrics


def validate_range(name, values, allow_zero=False):
    low, high = values
    minimum = 0.0 if allow_zero else np.nextafter(0.0, 1.0)
    if not math.isfinite(low) or not math.isfinite(high) or low < minimum or high <= low:
        qualifier = "non-negative" if allow_zero else "positive"
        raise CommandError(f"{name} must contain two increasing finite {qualifier} values")
    return float(low), float(high)


def sample_log_uniform(randomizer, bounds):
    low, high = bounds
    return math.exp(randomizer.uniform(math.log(low), math.log(high)))


def sample_parameters(randomizer, ranges):
    annual_drift_range = ranges.annual_drift
    if annual_drift_range[0] <= 0.0 and randomizer.random() < 0.25:
        annual_drift = 0.0
    elif annual_drift_range[0] <= 0.0 and annual_drift_range[1] <= 1.0:
        annual_drift = randomizer.uniform(*annual_drift_range)
    else:
        positive_low = annual_drift_range[0] if annual_drift_range[0] > 0.0 else 1.0
        annual_drift = sample_log_uniform(
            randomizer,
            (positive_low, annual_drift_range[1]),
        )
    return OptimizationParameters(
        weight_limit=sample_log_uniform(randomizer, ranges.weight_limit),
        sig_limit=sample_log_uniform(randomizer, ranges.sig_limit),
        sig_noob=sample_log_uniform(randomizer, ranges.sig_noob),
        annual_drift=annual_drift,
    )


class Command(BaseCommand):
    help = "Optimize Elo-MMR rating prediction parameters with a read-only walk-forward backtest"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger("ranking.optimize_rating_prediction")

    def add_arguments(self, parser):
        parser.add_argument("-r", "--resources", metavar="HOST", nargs="+", required=True, help="resource hosts")
        parser.add_argument("--trials", type=int, default=300, help="number of sampled parameter configurations")
        parser.add_argument("--seed", type=int, default=42, help="random seed")
        parser.add_argument("--burn-in-contests", type=int, default=5, help="initial contests excluded from scoring")
        parser.add_argument("--test-contests", type=int, default=5, help="latest contests reserved for testing")
        parser.add_argument("--half-life", type=float, default=8.0, help="training score half-life in contests")
        parser.add_argument("--top", type=int, default=10, help="number of training candidates to print")
        parser.add_argument(
            "--max-participants",
            type=int,
            default=DEFAULT_MAX_PARTICIPANTS,
            help="maximum participants per contest for exact all-pairs metrics",
        )
        parser.add_argument(
            "--show-contests", action="store_true", help="print current and optimized per-contest metrics"
        )
        parser.add_argument("--weight-limit-range", type=float, nargs=2, default=(0.03, 1.0), metavar=("MIN", "MAX"))
        parser.add_argument("--sig-limit-range", type=float, nargs=2, default=(20.0, 250.0), metavar=("MIN", "MAX"))
        parser.add_argument("--sig-noob-range", type=float, nargs=2, default=(100.0, 700.0), metavar=("MIN", "MAX"))
        parser.add_argument("--annual-drift-range", type=float, nargs=2, default=(0.0, 200.0), metavar=("MIN", "MAX"))

    @print_sql_decorator(count_only=True)
    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)
        self.validate_arguments(args)

        resources = Resource.get(args.resources, queryset=Resource.objects.filter(rating_prediction__isnull=False))
        for resource in resources:
            self.optimize_resource(resource, args)

    def validate_arguments(self, args):
        if args.trials < 1:
            raise CommandError("trials must be positive")
        if args.burn_in_contests < 0:
            raise CommandError("burn-in-contests must be non-negative")
        if args.test_contests < 1:
            raise CommandError("test-contests must be positive")
        if not math.isfinite(args.half_life) or args.half_life <= 0:
            raise CommandError("half-life must be a positive finite value")
        if args.top < 1:
            raise CommandError("top must be positive")
        if args.max_participants < 2:
            raise CommandError("max-participants must be at least two")
        args.parameter_ranges = AttrDict({
            "weight_limit": validate_range("weight-limit-range", args.weight_limit_range),
            "sig_limit": validate_range("sig-limit-range", args.sig_limit_range),
            "sig_noob": validate_range("sig-noob-range", args.sig_noob_range),
            "annual_drift": validate_range("annual-drift-range", args.annual_drift_range, allow_zero=True),
        })

    def optimize_resource(self, resource, args):
        config = resource.rating_prediction or {}
        if config.get("algorithm") != ELO_MMR_ALGORITHM:
            raise CommandError(f"resource {resource.host} does not use {ELO_MMR_ALGORITHM}")
        settings = get_elo_mmr_settings(resource)
        rated_contests = get_elo_mmr_rated_contests(resource, timezone.now(), settings.account_type)
        for contest, standings, _, _ in rated_contests:
            if len(standings) > args.max_participants:
                raise CommandError(
                    f"contest {contest.pk} has {len(standings)} participants, exceeding "
                    f"--max-participants={args.max_participants}; exact prediction metrics use O(n^2) memory"
                )
        train_stop = len(rated_contests) - args.test_contests
        if train_stop <= args.burn_in_contests:
            raise CommandError(
                f"resource {resource.host} needs more than "
                f"{args.burn_in_contests + args.test_contests} eligible contests"
            )

        current_rater = elo_mmr_py.Rater(settings.system, **settings.rate_kwargs)
        current_parameters = OptimizationParameters(
            weight_limit=config["weight_limit"],
            sig_limit=config["sig_limit"],
            sig_noob=current_rater.sig_noob,
            annual_drift=math.sqrt(config["drift_per_day"] * DAYS_PER_YEAR),
        )
        try:
            current_result = self.evaluate_candidate(
                rated_contests, config, current_parameters, args.burn_in_contests, train_stop, args.half_life
            )
        except ValueError as error:
            raise CommandError(f"resource {resource.host}: {error}") from error

        randomizer = random.Random(args.seed)
        results = [current_result]
        for _ in range(args.trials):
            parameters = sample_parameters(randomizer, args.parameter_ranges)
            results.append(
                self.evaluate_candidate(
                    rated_contests, config, parameters, args.burn_in_contests, train_stop, args.half_life
                )
            )
        results.sort(key=lambda result: (result.train.log_loss, result.train.rank_rmse))

        recommended_parameters = results[0].parameters.rounded()
        recommended_result = self.evaluate_candidate(
            rated_contests,
            config,
            recommended_parameters,
            args.burn_in_contests,
            train_stop,
            args.half_life,
        )
        if recommended_result.train.log_loss > current_result.train.log_loss:
            recommended_result = current_result
        results.append(recommended_result)
        results.sort(key=lambda result: (result.train.log_loss, result.train.rank_rmse))

        self.print_results(
            resource,
            rated_contests,
            current_result,
            recommended_result,
            results,
            train_stop,
            args,
        )

    @staticmethod
    def evaluate_candidate(rated_contests, config, parameters, train_start, train_stop, half_life):
        metrics = evaluate_elo_mmr_parameters(rated_contests, config, parameters)
        return AttrDict({
            "parameters": parameters,
            "metrics": metrics,
            "train": aggregate_prediction_metrics(metrics, train_start, train_stop, half_life),
            "test": aggregate_prediction_metrics(metrics, train_stop, len(rated_contests)),
        })

    def print_results(
        self,
        resource,
        rated_contests,
        current_result,
        recommended_result,
        results,
        train_stop,
        args,
    ):
        self.stdout.write("")
        self.stdout.write(f"Resource: {resource.host} ({resource.pk})")
        self.stdout.write(
            f"Eligible contests: {len(rated_contests)}, burn-in: {args.burn_in_contests}, "
            f"train: {train_stop - args.burn_in_contests}, test: {args.test_contests}, "
            f"scored: {len(current_result.metrics)}"
        )
        self.stdout.write(f"Candidate configurations: {args.trials + 1}")

        comparison = PrettyTable([
            "Config",
            "Weight limit",
            "Sig limit",
            "Sig noob",
            "Drift/day",
            "Train log loss",
            "Train pred.",
            "Train rank RMSE",
            "Test log loss",
            "Test pred.",
            "Test rank RMSE",
        ])
        self.add_result_row(comparison, "Current", current_result, include_test=True)
        self.add_result_row(comparison, "Optimized", recommended_result, include_test=True)
        self.stdout.write(str(comparison))

        top_results = PrettyTable([
            "#",
            "Weight limit",
            "Sig limit",
            "Sig noob",
            "Drift/day",
            "Train log loss",
            "Train pred.",
            "Train rank RMSE",
        ])
        for index, result in enumerate(results[: args.top], start=1):
            parameters = result.parameters
            top_results.add_row([
                index,
                f"{parameters.weight_limit:.2f}",
                f"{parameters.sig_limit:.1f}",
                f"{parameters.sig_noob:.1f}",
                f"{parameters.drift_per_day:.2f}",
                f"{result.train.log_loss:.6f}",
                f"{result.train.predictability:.4f}",
                f"{result.train.rank_rmse:.6f}",
            ])
        self.stdout.write("Top training configurations:")
        self.stdout.write(str(top_results))

        parameters = recommended_result.parameters
        override = {
            "weight_limit": parameters.weight_limit,
            "sig_limit": parameters.sig_limit,
            "sig_noob": parameters.sig_noob,
            "drift_per_day": round(parameters.drift_per_day, 2),
        }
        self.stdout.write("Suggested Resource.rating_prediction override:")
        self.stdout.write(json.dumps(override, indent=2, sort_keys=True))

        if args.show_contests:
            self.print_contest_metrics(current_result, recommended_result, train_stop, args)

    @staticmethod
    def add_result_row(table, name, result, include_test=False):
        parameters = result.parameters
        row = [
            name,
            f"{parameters.weight_limit:.2f}",
            f"{parameters.sig_limit:.1f}",
            f"{parameters.sig_noob:.1f}",
            f"{parameters.drift_per_day:.2f}",
            f"{result.train.log_loss:.6f}",
            f"{result.train.predictability:.4f}",
            f"{result.train.rank_rmse:.6f}",
        ]
        if include_test:
            row.extend([
                f"{result.test.log_loss:.6f}",
                f"{result.test.predictability:.4f}",
                f"{result.test.rank_rmse:.6f}",
            ])
        table.add_row(row)

    def print_contest_metrics(self, current_result, recommended_result, train_stop, args):
        table = PrettyTable([
            "Scope",
            "Year",
            "Contest",
            "N",
            "Current loss",
            "Optimized loss",
            "Current pred.",
            "Optimized pred.",
            "Current RMSE",
            "Optimized RMSE",
        ])
        table.max_width["Contest"] = 48
        for current, optimized in zip(current_result.metrics, recommended_result.metrics):
            if current.contest_index < args.burn_in_contests:
                scope = "burn-in"
            elif current.contest_index < train_stop:
                scope = "train"
            else:
                scope = "test"
            table.add_row([
                scope,
                current.contest.start_time.year,
                current.contest.title,
                current.n_participants,
                f"{current.log_loss:.6f}",
                f"{optimized.log_loss:.6f}",
                f"{current.predictability:.4f}",
                f"{optimized.predictability:.4f}",
                f"{current.rank_rmse:.6f}",
                f"{optimized.rank_rmse:.6f}",
            ])
        self.stdout.write("Per-contest metrics:")
        self.stdout.write(str(table))
