#!/usr/bin/env python3

import copy
import hashlib
import json
import tempfile
from collections import defaultdict
from logging import getLogger
from pathlib import Path

import elo_mmr_py
import numpy as np
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Case, F, FloatField, Q, When
from django.utils import timezone
from numba import njit
from prettytable import PrettyTable
from sql_util.utils import SubqueryCount

from clist.models import Contest, Resource
from clist.templatetags.extras import get_item
from logify import live as tqdm
from logify.live import register_live_logger
from logify.models import EventLog, EventStatus
from ranking.models import Account, Statistics
from utils.attrdict import AttrDict
from utils.json_field import FloatJSONF
from utils.logger import measure_time, suppress_db_logging_context

ELO_MMR_ALGORITHM = "elo_mmr_py"
ELO_MMR_CALCULATION_VERSION = "v3"
ELO_MMR_STATE_FIELD = "_elo_mmr_state"
ELO_MMR_PLAYER_STATE_FORMAT_VERSION = 2
ELO_MMR_RATING_FIELDS = ("old_rating", "new_rating", "rating_change", "rating_perf")
ELO_MMR_SYSTEM_SETTINGS = (
    "weight_limit",
    "noob_delay",
    "sig_limit",
    "drift_per_day",
    "split_ties",
    "subsample_size",
    "subsample_bucket",
)
ELO_MMR_REQUIRED_SETTINGS = (
    "algorithm",
    "algorithm_version",
    "initial_rating",
    "save_rating",
    "system",
    *ELO_MMR_SYSTEM_SETTINGS,
)


@njit
def E(delta: float):
    return 1 / (1 + 10 ** (-delta / 400))


@njit
def f(k: int):
    p = 5.0 / 7.0
    return 1 / (1 + 1 * (1 - p**k) / (1 - p))


@njit
def binary_search(arr, val):
    left = 0
    right = len(arr)
    while left < right:
        middle = (left + right) // 2
        if arr[middle] < val:
            left = middle + 1
        else:
            right = middle
    return left


@njit
def enough_rating_for_rank_mean(ratings, rating, rank_mean):
    e_rank = 1
    for r in ratings:
        e_rank += E(r - rating)
    return e_rank < rank_mean


@njit
def calculate_expected_ratings(ranks, ratings, rating_limit=10000):
    n = len(ranks)
    expected_ratings = np.zeros((n, 2), dtype=np.float64)
    ranks_ratings = zip(ranks, ratings)

    rank_means = []
    for index, (rank, rating) in enumerate(ranks_ratings):
        e_rank = 0
        for r in ratings:
            e_rank += E(r - rating)
        e_rank += 0.5
        rank_mean = (rank * e_rank) ** 0.5
        rank_means.append((rank_mean, 0, index))
        rank_means.append((rank + 0.5, 1, index))

    rank_means.sort()
    window_rating = float(rating_limit)
    rank_rating = float(rating_limit)
    for rank_mean, field, index in rank_means:
        right = rank_rating

        while right - window_rating > 0 and enough_rating_for_rank_mean(ratings, right - window_rating, rank_mean):
            window_rating *= 2
        if not enough_rating_for_rank_mean(ratings, right - window_rating / 2, rank_mean):
            window_rating /= 2

        left = max(right - window_rating, 0)
        while right - left > 1e-3:
            middle = (left + right) / 2
            if enough_rating_for_rank_mean(ratings, middle, rank_mean):
                right = middle
            else:
                left = middle
        rank_rating = right
        expected_ratings[index][field] = rank_rating

    return expected_ratings


def calculate_rating_prediction(rankings):
    assert len(rankings) > 1

    rankings.sort(key=lambda r: r["old_rating"])
    ranks = np.array([r["rank"] for r in rankings])
    ratings = np.array([r["old_rating"] for r in rankings])
    expected_ratings = calculate_expected_ratings(ranks, ratings)
    for ranking, expected_rating in zip(rankings, expected_ratings):
        expected_rating = dict(zip(["rating", "perf"], expected_rating))
        rating_change = f(ranking["n_contests"]) * (expected_rating["rating"] - ranking["old_rating"])
        ranking["rating_perf"] = expected_rating["perf"]
        ranking["rating_change"] = rating_change
    return True


def get_old_ratings(contest):
    resource = contest.resource
    accounts = Statistics.objects.filter(contest=contest, place_as_int__isnull=False).values("account_id")

    rating_field = resource.rating_prediction.get("rating_field", "new_rating")
    latest_rating = (
        Statistics.objects
        .filter(
            contest__start_time__lt=contest.start_time,
            contest__resource=resource,
            account__in=accounts,
        )
        .exclude(
            contest__is_rated=False,
        )
        .annotate(
            latest_rating=Case(
                When(**{f"addition__{rating_field}__isnull": False}, then=FloatJSONF(f"addition__{rating_field}")),
                When(rating_prediction__isnull=False, then=FloatJSONF(f"rating_prediction__{rating_field}")),
                output_field=FloatField(),
            ),
            member=F("account__key"),
        )
        .filter(
            account__rating__isnull=False,
            latest_rating__isnull=False,
        )
        .order_by("account", "-contest__end_time")
        .distinct("account")
        .values("member", "latest_rating")
    )

    n_contests_filter = Q(contest__start_time__lt=contest.start_time, skip_in_stats=False)
    n_contests_filter &= Q(contest__is_rated=True) | Q(contest__is_rated__isnull=True)
    statistics = (
        Statistics.objects
        .filter(
            contest=contest,
            account__in=accounts,
        )
        .filter(
            place_as_int__isnull=False,
        )
        .annotate(
            rank=F("place_as_int"),
            member=F("account__key"),
            n_contests=SubqueryCount("account__statistics", filter=n_contests_filter),
        )
    )

    rankings = {}
    for statistic in statistics:
        ranking = {
            "rank": statistic.rank,
            "member": statistic.member,
            "n_contests": statistic.n_contests,
        }
        old_rating = statistic.get_old_rating(use_rating_prediction=False)
        if old_rating is not None:
            ranking["old_rating"] = old_rating
        rankings[ranking["member"]] = ranking
    for account in latest_rating:
        rankings[account["member"]].setdefault("old_rating", account["latest_rating"])
    rankings = list(rankings.values())
    for ranking in rankings:
        if ranking.get("old_rating") is None:
            ranking["old_rating"] = resource.rating_prediction["initial_rating"]
        ranking["n_contests"] += 1

    rankings.sort(key=lambda r: r["rank"])
    return rankings


def get_elo_mmr_settings(resource):
    config = resource.rating_prediction or {}
    missing_fields = [field for field in ELO_MMR_REQUIRED_SETTINGS if field not in config]
    if missing_fields:
        raise ValueError(f"missing required Elo-MMR settings: {', '.join(missing_fields)}")

    if config["algorithm"] != ELO_MMR_ALGORITHM:
        raise ValueError(f"unexpected Elo-MMR algorithm = {config['algorithm']!r}")
    if config["algorithm_version"] != elo_mmr_py.__version__:
        raise ValueError(
            f"elo_mmr_py version mismatch: configured {config['algorithm_version']}, installed {elo_mmr_py.__version__}"
        )

    account_type_name = config.get("account_type")
    account_type = None
    if account_type_name is not None:
        account_type = Account.get_type(account_type_name)
        if account_type is None:
            raise ValueError(f"unknown account_type = {account_type_name!r}")
        account_type_name = Account.get_type_value(account_type)

    system_kwargs = {field: config[field] for field in ELO_MMR_SYSTEM_SETTINGS}
    system = elo_mmr_py.EloMmrConfig(config["system"], **system_kwargs)
    rate_kwargs = {"mu_noob": config["initial_rating"]}
    if "sig_noob" in config:
        rate_kwargs["sig_noob"] = config["sig_noob"]
    return AttrDict({
        "account_type": account_type,
        "account_type_name": account_type_name,
        "initial_rating": config["initial_rating"],
        "rate_kwargs": rate_kwargs,
        "save_rating": config["save_rating"],
        "system": system,
    })


def get_elo_mmr_standings(contest, account_type=None):
    statistics = Statistics.objects.filter(
        contest=contest,
        place_as_int__isnull=False,
        skip_in_stats=False,
    )
    if account_type is not None:
        statistics = statistics.filter(account__account_type=account_type)
    statistics = list(
        statistics.order_by("place_as_int", "account_id").values("pk", "account_id", "account__key", "place_as_int")
    )

    standings = []
    participants = {}
    index = 0
    while index < len(statistics):
        end = index + 1
        while end < len(statistics) and statistics[end]["place_as_int"] == statistics[index]["place_as_int"]:
            end += 1
        low_rank = index
        high_rank = end - 1
        for statistic in statistics[index:end]:
            participant = str(statistic["account_id"])
            standings.append((participant, low_rank, high_rank))
            participants[participant] = statistic
        index = end
    return standings, participants


def get_elo_mmr_rated_contests(resource, now, account_type=None):
    rated_contests = []
    eligible_contests = Contest.objects.filter(
        resource=resource,
        stage__isnull=True,
        start_time__lt=now,
    ).order_by("start_time", "pk")
    for contest in eligible_contests:
        if not contest.is_finalized() or not contest.is_major_kind():
            continue
        standings, participants = get_elo_mmr_standings(contest, account_type)
        if len(standings) < 2:
            continue
        native_contest = elo_mmr_py.Contest(
            standings,
            name=contest.title,
            time_seconds=int(contest.end_time.timestamp()),
            url=contest.actual_url,
        )
        rated_contests.append((contest, standings, participants, native_contest))
    return rated_contests


def get_elo_mmr_player_state_hash(player):
    return hashlib.sha256(json.dumps(player, sort_keys=True, separators=(",", ":")).encode("utf8")).hexdigest()


def apply_elo_mmr_player_state(previous_player, stored_player_state):
    """Restore the package checkpoint player from one persisted full state or delta."""
    if not isinstance(stored_player_state, dict):
        raise ValueError("invalid Elo-MMR stored player state")

    state_type = stored_player_state.get("type")
    if state_type == "full":
        player = stored_player_state.get("player")
        if not isinstance(player, dict):
            raise ValueError("invalid Elo-MMR full player state")
        return copy.deepcopy(player)
    if state_type != "delta":
        raise ValueError(f"invalid Elo-MMR stored player state type = {state_type!r}")
    if not isinstance(previous_player, dict):
        raise ValueError("missing previous Elo-MMR player state for delta")

    fields = stored_player_state.get("fields")
    event = stored_player_state.get("event")
    logistic_factor = stored_player_state.get("logistic_factor")
    logistic_factor_scale = stored_player_state.get("logistic_factor_scale")
    if not isinstance(fields, dict) or "event_history" in fields or "logistic_factors" in fields:
        raise ValueError("invalid Elo-MMR player delta fields")
    if not isinstance(event, dict) or not isinstance(logistic_factor, dict):
        raise ValueError("invalid Elo-MMR player delta event")
    if not isinstance(logistic_factor_scale, int | float):
        raise ValueError("invalid Elo-MMR player delta logistic factor scale")

    player = copy.deepcopy(previous_player)
    if not isinstance(player.get("event_history"), list) or not isinstance(player.get("logistic_factors"), list):
        raise ValueError("invalid previous Elo-MMR player history")
    for previous_logistic_factor in player["logistic_factors"]:
        if not isinstance(previous_logistic_factor, dict) or not isinstance(
            previous_logistic_factor.get("w_out"), int | float
        ):
            raise ValueError("invalid previous Elo-MMR logistic factor")
        previous_logistic_factor["w_out"] *= logistic_factor_scale
    player.update(copy.deepcopy(fields))
    player["event_history"].append(copy.deepcopy(event))
    player["logistic_factors"].append(copy.deepcopy(logistic_factor))
    return player


def make_elo_mmr_player_state(previous_player, player):
    """Persist one event when old logistic factors differ only by their common weight scale."""

    def make_full_state():
        return {"type": "full", "player": copy.deepcopy(player)}

    if not isinstance(previous_player, dict) or previous_player.keys() != player.keys():
        return make_full_state()

    try:
        previous_event_history = previous_player["event_history"]
        event_history = player["event_history"]
        previous_logistic_factors = previous_player["logistic_factors"]
        logistic_factors = player["logistic_factors"]
        if not all(
            isinstance(history, list)
            for history in (previous_event_history, event_history, previous_logistic_factors, logistic_factors)
        ):
            return make_full_state()
        if event_history[: len(previous_event_history)] != previous_event_history:
            return make_full_state()
        if len(logistic_factors) < len(previous_logistic_factors):
            return make_full_state()
        new_events = event_history[len(previous_event_history) :]
        new_logistic_factors = logistic_factors[len(previous_logistic_factors) :]
        if len(new_events) != 1 or len(new_logistic_factors) != 1:
            return make_full_state()

        logistic_factor_scale = None
        for previous_factor, factor in zip(previous_logistic_factors, logistic_factors):
            previous_factor_without_weight = {key: value for key, value in previous_factor.items() if key != "w_out"}
            factor_without_weight = {key: value for key, value in factor.items() if key != "w_out"}
            if previous_factor_without_weight != factor_without_weight:
                return make_full_state()
            previous_weight = previous_factor["w_out"]
            weight = factor["w_out"]
            if previous_weight:
                scale = weight / previous_weight
                if logistic_factor_scale is None:
                    logistic_factor_scale = scale
                elif previous_weight * logistic_factor_scale != weight:
                    return make_full_state()
            elif weight:
                return make_full_state()
        if logistic_factor_scale is None:
            logistic_factor_scale = 1.0
        if any(
            previous_factor["w_out"] * logistic_factor_scale != factor["w_out"]
            for previous_factor, factor in zip(previous_logistic_factors, logistic_factors)
        ):
            return make_full_state()

        stored_player_state = {
            "type": "delta",
            "fields": {
                key: copy.deepcopy(value)
                for key, value in player.items()
                if key not in ("event_history", "logistic_factors")
            },
            "event": copy.deepcopy(new_events[0]),
            "logistic_factor": copy.deepcopy(new_logistic_factors[0]),
            "logistic_factor_scale": logistic_factor_scale,
        }
        if apply_elo_mmr_player_state(previous_player, stored_player_state) != player:
            return make_full_state()
        return stored_player_state
    except AttributeError, KeyError, TypeError, ZeroDivisionError:
        return make_full_state()


def get_elo_mmr_checkpoint(resource, rated_contests, start_index, account_type=None):
    previous_contest = rated_contests[start_index - 1][0]
    calculation = get_item(previous_contest, "info._rating_calculation") or {}
    expected_metadata = {
        "algorithm": ELO_MMR_ALGORITHM,
        "algorithm_version": elo_mmr_py.__version__,
        "calculation_version": ELO_MMR_CALCULATION_VERSION,
        "config": resource.rating_prediction,
    }
    for field, expected in expected_metadata.items():
        if calculation.get(field) != expected:
            raise ValueError(
                f"incompatible Elo-MMR checkpoint {field} = {calculation.get(field)!r}, expected {expected!r}; "
                "run a full resource replay"
            )

    checkpoint = calculation.get("checkpoint")
    if not isinstance(checkpoint, dict):
        raise ValueError("missing Elo-MMR checkpoint; run a full resource replay")
    if checkpoint.get("format_version") != elo_mmr_py.CHECKPOINT_FORMAT_VERSION:
        raise ValueError(
            f"incompatible Elo-MMR checkpoint format_version = {checkpoint.get('format_version')!r}, "
            f"expected {elo_mmr_py.CHECKPOINT_FORMAT_VERSION!r}; run a full resource replay"
        )
    if checkpoint.get("contests_processed") != start_index:
        raise ValueError(
            f"incompatible Elo-MMR checkpoint contests_processed = {checkpoint.get('contests_processed')!r}, "
            f"expected {start_index!r}; run a full resource replay"
        )

    participant_statistics = defaultdict(list)
    for contest, _, participants, _ in rated_contests[:start_index]:
        for participant, statistic in participants.items():
            participant_statistics[participant].append((statistic["pk"], contest))
    statistics = Statistics.objects.filter(
        contest_id__in=[contest.pk for contest, _, _, _ in rated_contests[:start_index]],
        place_as_int__isnull=False,
        skip_in_stats=False,
    )
    if account_type is not None:
        statistics = statistics.filter(account__account_type=account_type)
    statistics = dict(statistics.values_list("pk", "rating_prediction"))

    players = {}
    expected_state_metadata = {
        "algorithm": ELO_MMR_ALGORITHM,
        "algorithm_version": elo_mmr_py.__version__,
        "calculation_version": ELO_MMR_CALCULATION_VERSION,
        "checkpoint_format_version": elo_mmr_py.CHECKPOINT_FORMAT_VERSION,
        "player_state_format_version": ELO_MMR_PLAYER_STATE_FORMAT_VERSION,
    }
    for participant, participant_history in participant_statistics.items():
        player = None
        for statistic_id, contest in participant_history:
            prediction = statistics[statistic_id] or {}
            state = prediction.get(ELO_MMR_STATE_FIELD) or {}
            for field, expected in expected_state_metadata.items():
                if state.get(field) != expected:
                    raise ValueError(
                        f"incompatible Elo-MMR statistic checkpoint {field} = {state.get(field)!r}, "
                        f"expected {expected!r}, statistic = {statistic_id}; run a full resource replay"
                    )
            if state.get("input_hash") != contest.rating_prediction_hash:
                raise ValueError(
                    f"incompatible Elo-MMR statistic checkpoint input_hash, statistic = {statistic_id}; "
                    "run a full resource replay"
                )
            try:
                player = apply_elo_mmr_player_state(player, state.get("player_state"))
            except ValueError as error:
                raise ValueError(
                    f"invalid Elo-MMR statistic checkpoint player_state, statistic = {statistic_id}; "
                    "run a full resource replay"
                ) from error
            if state.get("state_hash") != get_elo_mmr_player_state_hash(player):
                raise ValueError(
                    f"invalid Elo-MMR statistic checkpoint state_hash, statistic = {statistic_id}; "
                    "run a full resource replay"
                )
        players[participant] = player

    return {**checkpoint, "players": players}, previous_contest.rating_prediction_hash


def calculate_elo_mmr_replay(resource, now, start_time=None):
    settings = get_elo_mmr_settings(resource)
    contests = list(Contest.objects.filter(resource=resource).order_by("start_time", "pk"))
    rated_contests = get_elo_mmr_rated_contests(resource, now, settings.account_type)

    rated_contest_ids = [contest.pk for contest, _, _, _ in rated_contests]
    rated_contest_ids_set = set(rated_contest_ids)
    invalidated_contests = []
    for contest in contests:
        algorithm = get_item(contest, "info._rating_calculation.algorithm")
        if algorithm != ELO_MMR_ALGORITHM or contest.pk in rated_contest_ids_set:
            continue
        if start_time is None or contest.start_time >= start_time:
            invalidated_contests.append(contest)

    if not rated_contests:
        return AttrDict(
            settings=settings,
            snapshots=[],
            latest={},
            final={},
            leaderboard=[],
            rated_contest_ids=[],
            invalidated_contests=invalidated_contests,
        )

    start_index = 0
    if start_time is not None:
        while start_index < len(rated_contests) and rated_contests[start_index][0].start_time < start_time:
            start_index += 1
    checkpoint = None
    previous_hash = None
    if start_index:
        checkpoint, previous_hash = get_elo_mmr_checkpoint(
            resource, rated_contests, start_index, account_type=settings.account_type
        )

    snapshots = []
    latest = {}
    config = resource.rating_prediction or {}
    with tempfile.TemporaryDirectory(prefix="clist-elo-mmr-") as temporary_directory:
        checkpoint_path = Path(temporary_directory) / "checkpoint.json"
        if checkpoint is None:
            rater = elo_mmr_py.Rater(settings.system, **settings.rate_kwargs)
        else:
            checkpoint_path.write_text(json.dumps(checkpoint, separators=(",", ":")), encoding="utf8")
            rater = elo_mmr_py.Rater.load(checkpoint_path)

        previous_players = checkpoint["players"] if checkpoint is not None else {}
        for contest_index in range(start_index, len(rated_contests)):
            contest, standings, participants, native_contest = rated_contests[contest_index]
            rater.add(native_contest)
            rater.save(checkpoint_path)
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf8"))
            if checkpoint["contests_processed"] != contest_index + 1:
                raise ValueError("unexpected Elo-MMR checkpoint contest index")

            hash_payload = {
                "calculation_version": ELO_MMR_CALCULATION_VERSION,
                "package_version": elo_mmr_py.__version__,
                "config": config,
                "previous_hash": previous_hash,
                "contest": contest.pk,
                "time": int(contest.end_time.timestamp()),
                "standings": standings,
            }
            input_hash = hashlib.sha256(
                json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode("utf8")
            ).hexdigest()

            rankings = []
            for participant, _, _ in standings:
                player = checkpoint["players"][participant]
                event_history = player["event_history"]
                event = event_history[-1]
                if event["contest_index"] != contest_index:
                    raise ValueError("unexpected Elo-MMR player event contest index")
                old_rating = (
                    event_history[-2]["rating_mu"] if len(event_history) > 1 else round(settings.initial_rating)
                )
                new_rating = event["rating_mu"]
                player_state = {
                    "algorithm": ELO_MMR_ALGORITHM,
                    "algorithm_version": elo_mmr_py.__version__,
                    "calculation_version": ELO_MMR_CALCULATION_VERSION,
                    "checkpoint_format_version": elo_mmr_py.CHECKPOINT_FORMAT_VERSION,
                    "player_state_format_version": ELO_MMR_PLAYER_STATE_FORMAT_VERSION,
                    "input_hash": input_hash,
                    "player_state": make_elo_mmr_player_state(previous_players.get(participant), player),
                }
                player_state["state_hash"] = get_elo_mmr_player_state_hash(player)
                statistic = participants[participant]
                prediction = {
                    "rank": statistic["place_as_int"],
                    "old_rating": old_rating,
                    "new_rating": new_rating,
                    "rating_change": new_rating - old_rating,
                    "rating_perf": event["perf_score"],
                    "rating_sig": event["rating_sig"],
                    "n_contests": len(event_history),
                    ELO_MMR_STATE_FIELD: player_state,
                }
                ranking = {
                    "account_id": statistic["account_id"],
                    "member": statistic["account__key"],
                    "statistic_id": statistic["pk"],
                    "prediction": prediction,
                }
                rankings.append(ranking)
                latest[participant] = {"contest": contest, **ranking}

            checkpoint_metadata = {key: value for key, value in checkpoint.items() if key != "players"}
            snapshots.append(
                AttrDict(
                    contest=contest,
                    rankings=rankings,
                    input_hash=input_hash,
                    previous_hash=previous_hash,
                    checkpoint=checkpoint_metadata,
                )
            )
            previous_hash = input_hash
            previous_players = checkpoint["players"]

    final = {}
    leaderboard = []
    for participant, player in checkpoint["players"].items():
        event_history = player["event_history"]
        event = event_history[-1]
        old_rating = event_history[-2]["rating_mu"] if len(event_history) > 1 else round(settings.initial_rating)
        contest, _, participants, _ = rated_contests[event["contest_index"]]
        statistic = participants[participant]
        ranking = {
            "account_id": statistic["account_id"],
            "member": statistic["account__key"],
            "statistic_id": statistic["pk"],
            "prediction": {
                "rank": statistic["place_as_int"],
                "old_rating": old_rating,
                "new_rating": event["rating_mu"],
                "rating_change": event["rating_mu"] - old_rating,
                "rating_perf": event["perf_score"],
                "rating_sig": event["rating_sig"],
                "n_contests": len(event_history),
            },
        }
        final[participant] = {"contest": contest, **ranking}
        leaderboard.append(ranking)

    return AttrDict({
        "settings": settings,
        "snapshots": snapshots,
        "latest": latest,
        "final": final,
        "leaderboard": leaderboard,
        "rated_contest_ids": rated_contest_ids,
        "invalidated_contests": invalidated_contests,
    })


def add_elo_mmr_rating_fields(contest, account_type_name):
    fields = contest.info.setdefault("fields", [])
    fields_types = contest.info.setdefault("fields_types", {})
    for field in ELO_MMR_RATING_FIELDS:
        if field not in fields:
            fields.append(field)
        fields_types[field] = ["int"]

    standings = contest.info.setdefault("standings", {})
    if account_type_name:
        account_type_fields = standings.setdefault("account_type_fields", {})
        fixed_fields = account_type_fields.setdefault(account_type_name, {}).setdefault("fixed_fields", [])
    else:
        fixed_fields = standings.setdefault("fixed_fields", [])
    for field in ELO_MMR_RATING_FIELDS:
        if field not in fixed_fields:
            fixed_fields.append(field)


class Command(BaseCommand):
    help = "Calculate rating prediction"
    VERSION = "v1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger("ranking.calculate_rating_prediction")

    def add_arguments(self, parser):
        parser.add_argument("-r", "--resources", metavar="HOST", nargs="*", help="host names to calculate")
        parser.add_argument("-c", "--contest", metavar="CONTEST", type=int, help="contest id")
        parser.add_argument("-cs", "--contests", metavar="CONTESTS", nargs="*", type=int, help="contest ids")
        parser.add_argument("-s", "--search", metavar="TITLE", help="contest title regex")
        parser.add_argument("-l", "--limit", metavar="LIMIT", type=int, help="limit contests")
        parser.add_argument("-f", "--force", action="store_true", help="force update")
        parser.add_argument("--dryrun", action="store_true", help="calculate and print without saving")

    def handle(self, *_, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)
        register_live_logger(self.logger)

        resources = Resource.objects.all()
        if args.resources:
            resources = Resource.get(args.resources, queryset=resources)
        else:
            resources = resources.filter(rating_prediction__isnull=False)
        resources = list(resources)
        self.logger.info(f"resources = {[resource.host for resource in resources]}")

        now = timezone.now()
        has_contest_selector = bool(args.search or args.contest or args.contests or args.limit)
        if not has_contest_selector and not args.resources:
            self.logger.warning("no contests or resources specified")
            return

        contests = Contest.objects.filter(resource__in=resources, stage__isnull=True, start_time__lt=now)
        if args.search:
            contests = contests.filter(title__regex=args.search)
        elif args.contest:
            contests = contests.filter(pk=args.contest)
        elif args.contests:
            contests = contests.filter(pk__in=args.contests)
        elif args.limit:
            contests = contests.order_by("-end_time")
            contests = contests[: args.limit]
        contests = sorted(contests, key=lambda contest: (contest.start_time, contest.pk))

        self.logger.info(f"contests = {[c.title for c in contests]}")
        for resource in resources:
            resource_contests = [contest for contest in contests if contest.resource_id == resource.pk]
            algorithm = get_item(resource, "rating_prediction.algorithm")
            if algorithm == ELO_MMR_ALGORITHM:
                if has_contest_selector and not resource_contests:
                    continue
                self.process_elo_mmr_resource(resource, resource_contests, now, args)
            else:
                if algorithm:
                    raise ValueError(f"unknown rating prediction algorithm = {algorithm!r}")
                if not has_contest_selector:
                    self.logger.warning(
                        f"skip legacy rating prediction without contest selector, resource = {resource}"
                    )
                    continue
                if not resource_contests:
                    self.logger.warning(f"no contests specified for legacy rating prediction, resource = {resource}")
                for contest in resource_contests:
                    self.process_legacy_contest(contest, now, args)

    def process_legacy_contest(self, contest, now, args):
        resource = contest.resource
        skip_action = "skip" if not args.force else "ignore skipping"

        if not contest.is_rating_prediction_timespan:
            self.logger.warning(f"{skip_action} contest with timespan, contest = {contest}")
            if not args.force:
                return

        event_log = None
        if not args.dryrun:
            event_log = EventLog.objects.create(
                name="calculate_rating_prediction", related=contest, status=EventStatus.IN_PROGRESS
            )

        with measure_time("get_old_ratings", logger=self.logger):
            rankings = get_old_ratings(contest)

        if len(rankings) < 2:
            self.logger.warning(f"skip contest with less than two rankings, contest = {contest}")
            if event_log:
                event_log.update_status(EventStatus.SKIPPED, message="not enough rankings")
            return

        values = (tuple(r[f] for f in ("rank", "member", "old_rating", "n_contests")) for r in rankings)
        values = tuple(sorted(values))
        values = (self.VERSION, values)
        rating_prediction_hash = hashlib.sha256(str(values).encode("utf8")).hexdigest()

        if contest.rating_prediction_hash == rating_prediction_hash:
            self.logger.warning(f"{skip_action} unchanged rating prediction hash, contest = {contest}")
            if not args.force and not args.dryrun:
                if event_log:
                    event_log.update_status(EventStatus.SKIPPED, message="unchanged rating prediction hash")
                return

        with measure_time("calculate_rating_prediction", logger=self.logger):
            calculate_rating_prediction(rankings)

        for ranking in rankings:
            if "rating_field" in resource.rating_prediction:
                ndigits = resource.rating_prediction.get("rating_round")
                rating = ranking["old_rating"] + ranking["rating_change"]
                ranking[resource.rating_prediction["rating_field"]] = round(rating, ndigits)
            for field in "rating_perf", "rating_change":
                ranking[field] = round(ranking[field])
            ranking["new_rating"] = round(ranking["old_rating"]) + ranking["rating_change"]

        rankings.sort(key=lambda r: r["rank"])
        fields = [*rankings[0], "change_diff"]
        table = PrettyTable(field_names=fields)
        for ranking in rankings[:10]:
            stat = Statistics.objects.get(contest=contest, account__key=ranking["member"])
            prev_prediction = stat.rating_prediction
            if prev_prediction and "rating_change" in prev_prediction and "rating_change" in ranking:
                ranking["change_diff"] = ranking.get("rating_change") - prev_prediction["rating_change"]
            table.add_row([ranking.get(field, "") for field in fields])
        self.stdout.write(str(table))

        if args.dryrun:
            return

        with transaction.atomic(), suppress_db_logging_context():
            rankings_dict = {ranking.pop("member"): ranking for ranking in rankings}
            statistics = Statistics.objects.filter(contest=contest).select_related("account")
            has_fixed_field = False
            fields_types = defaultdict(set)
            time = int(min(contest.end_time, now).timestamp())
            for stat in tqdm.tqdm(
                statistics.iterator(), total=contest.n_statistics, desc="update statistics rating predictions"
            ):
                account = stat.account
                if account.key not in rankings_dict:
                    continue
                if "rating_change" not in stat.addition:
                    has_fixed_field = True
                rating_prediction = rankings_dict[account.key]
                for key, value in rating_prediction.items():
                    fields_types[key].add(type(value).__name__)
                stat.rating_prediction = rating_prediction
                stat.save(update_fields=["rating_prediction"])

                rating_prediction["time"] = time
                rating_prediction["contest"] = contest.pk
                if (
                    not account.rating_prediction
                    or account.rating_prediction.get("contest") == rating_prediction["contest"]
                    or account.rating_prediction.get("time", 0) < rating_prediction["time"]
                ):
                    account.rating_prediction = rating_prediction
                    account.save(update_fields=["rating_prediction"])

            fields_types = {key: list(value) for key, value in fields_types.items()}

            rating_prediction_fields = contest.rating_prediction_fields or {}
            rating_prediction_fields["types"] = fields_types

            contest.rating_prediction_fields = rating_prediction_fields
            contest.rating_prediction_hash = rating_prediction_hash
            contest.has_fixed_rating_prediction_field = has_fixed_field
            contest.rating_prediction_timing = now
            contest.save(
                update_fields=[
                    "rating_prediction_hash",
                    "rating_prediction_timing",
                    "has_fixed_rating_prediction_field",
                    "rating_prediction_fields",
                ]
            )
        event_log.update_status(EventStatus.COMPLETED)

    def process_elo_mmr_resource(self, resource, selected_contests, now, args):
        first_start_time = None
        if selected_contests:
            first_start_time = min(contest.start_time for contest in selected_contests)
        with measure_time("calculate_elo_mmr_replay", logger=self.logger):
            replay = calculate_elo_mmr_replay(resource, now, start_time=first_start_time)
        if not replay.snapshots and not replay.invalidated_contests:
            self.logger.warning(f"skip resource without eligible Elo-MMR contests, resource = {resource}")
            return

        affected = replay.snapshots

        self.print_elo_mmr_top(replay)
        changed = [
            snapshot
            for snapshot in affected
            if args.force or snapshot.contest.rating_prediction_hash != snapshot.input_hash
        ]
        self.logger.info(
            f"Elo-MMR replay resource = {resource}, affected = {len(affected)}, changed = {len(changed)}, "
            f"invalidated = {len(replay.invalidated_contests)}"
        )
        if args.dryrun:
            return
        if not changed and not replay.invalidated_contests:
            self.logger.warning(f"skip unchanged Elo-MMR replay, resource = {resource}")
            return

        event_log = EventLog.objects.create(
            name="calculate_rating_prediction", related=resource, status=EventStatus.IN_PROGRESS
        )
        try:
            with transaction.atomic(), suppress_db_logging_context():
                resource = Resource.objects.select_for_update().get(pk=resource.pk)
                contest_ids_to_lock = replay.rated_contest_ids + [contest.pk for contest in replay.invalidated_contests]
                list(
                    Contest.objects.select_for_update().filter(pk__in=contest_ids_to_lock).values_list("pk", flat=True)
                )

                replay = calculate_elo_mmr_replay(resource, now, start_time=first_start_time)
                affected = replay.snapshots
                changed = [
                    snapshot
                    for snapshot in affected
                    if args.force or snapshot.contest.rating_prediction_hash != snapshot.input_hash
                ]
                if not changed and not replay.invalidated_contests:
                    event_log.update_status(EventStatus.SKIPPED, message="unchanged after acquiring contest locks")
                    return

                for contest in replay.invalidated_contests:
                    self.invalidate_elo_mmr_contest(contest)
                for snapshot in changed:
                    self.save_elo_mmr_snapshot(resource, replay.settings, snapshot, now)
                self.save_elo_mmr_accounts(resource, replay, now)
        except Exception as error:
            event_log.update_status(EventStatus.FAILED, message=str(error))
            raise
        event_log.update_status(
            EventStatus.COMPLETED,
            message=(
                f"updated {len(changed)} of {len(affected)} contests, "
                f"invalidated {len(replay.invalidated_contests)} contests"
            ),
        )

    @staticmethod
    def clear_elo_mmr_statistics(statistics):
        statistics_to_update = []
        for statistic in statistics:
            if get_item(statistic, ("rating_prediction", ELO_MMR_STATE_FIELD, "algorithm")) != ELO_MMR_ALGORITHM:
                continue
            statistic.rating_prediction = None
            addition = dict(statistic.addition or {})
            for field in ELO_MMR_RATING_FIELDS:
                addition.pop(field, None)
            statistic.addition = addition
            statistics_to_update.append(statistic)
        if statistics_to_update:
            Statistics.objects.bulk_update(statistics_to_update, ["rating_prediction", "addition"])

    def invalidate_elo_mmr_contest(self, contest):
        self.clear_elo_mmr_statistics(Statistics.objects.filter(contest=contest))

        contest.info = dict(contest.info or {})
        calculation = contest.info.pop("_rating_calculation", {}) or {}
        update_fields = [
            "info",
            "rating_prediction_fields",
            "rating_prediction_hash",
            "rating_prediction_timing",
            "has_fixed_rating_prediction_field",
        ]
        contest.rating_prediction_fields = {}
        contest.rating_prediction_hash = None
        contest.rating_prediction_timing = None
        contest.has_fixed_rating_prediction_field = False
        if get_item(calculation, "config.save_rating"):
            fields = contest.info.get("fields", [])
            contest.info["fields"] = [field for field in fields if field not in ELO_MMR_RATING_FIELDS]
            fields_types = contest.info.get("fields_types", {})
            for field in ELO_MMR_RATING_FIELDS:
                fields_types.pop(field, None)
            standings = contest.info.get("standings", {})
            fixed_fields_groups = [standings.get("fixed_fields", [])]
            fixed_fields_groups.extend(
                options.get("fixed_fields", []) for options in standings.get("account_type_fields", {}).values()
            )
            for fixed_fields in fixed_fields_groups:
                fixed_fields[:] = [field for field in fixed_fields if field not in ELO_MMR_RATING_FIELDS]
            contest.is_rated = False
            update_fields.append("is_rated")
        contest.save(update_fields=update_fields)

    def save_elo_mmr_snapshot(self, resource, settings, snapshot, now):
        contest = snapshot.contest
        rankings = {ranking["statistic_id"]: ranking for ranking in snapshot.rankings}
        self.clear_elo_mmr_statistics(Statistics.objects.filter(contest=contest).exclude(pk__in=rankings))
        statistics = Statistics.objects.filter(pk__in=rankings).in_bulk()
        fields_types = defaultdict(set)
        statistics_to_update = []
        statistic_update_fields = ["rating_prediction"]
        if settings.save_rating:
            statistic_update_fields.append("addition")
        for statistic_id, ranking in rankings.items():
            statistic = statistics[statistic_id]
            prediction = dict(ranking["prediction"])
            for key, value in prediction.items():
                if key == ELO_MMR_STATE_FIELD:
                    continue
                fields_types[key].add(type(value).__name__)
            statistic.rating_prediction = prediction
            if settings.save_rating:
                addition = dict(statistic.addition or {})
                addition.update({field: prediction[field] for field in ELO_MMR_RATING_FIELDS})
                statistic.addition = addition
            statistics_to_update.append(statistic)
        if statistics_to_update:
            Statistics.objects.bulk_update(statistics_to_update, statistic_update_fields)

        fields_types = {key: sorted(value) for key, value in fields_types.items()}
        rating_prediction_fields = dict(contest.rating_prediction_fields or {})
        rating_prediction_fields["types"] = fields_types
        contest.rating_prediction_fields = rating_prediction_fields
        contest.rating_prediction_hash = snapshot.input_hash
        contest.has_fixed_rating_prediction_field = True
        contest.rating_prediction_timing = now
        contest.info = dict(contest.info or {})
        contest.info["_rating_calculation"] = {
            "algorithm": ELO_MMR_ALGORITHM,
            "algorithm_version": elo_mmr_py.__version__,
            "package_version": elo_mmr_py.__version__,
            "calculation_version": ELO_MMR_CALCULATION_VERSION,
            "config": resource.rating_prediction,
            "checkpoint": snapshot.checkpoint,
            "input_hash": snapshot.input_hash,
            "calculated_at": now.isoformat(),
        }
        update_fields = [
            "rating_prediction_fields",
            "rating_prediction_hash",
            "has_fixed_rating_prediction_field",
            "rating_prediction_timing",
            "info",
        ]
        if settings.save_rating:
            add_elo_mmr_rating_fields(contest, settings.account_type_name)
            contest.is_rated = True
            update_fields.append("is_rated")
        contest.save(update_fields=update_fields)

    def save_elo_mmr_accounts(self, resource, replay, now):
        latest_account_ids = [int(participant) for participant in replay.latest]
        affected_contest_ids = [snapshot.contest.pk for snapshot in replay.snapshots]
        affected_contest_ids.extend(contest.pk for contest in replay.invalidated_contests)
        accounts = (
            Account.objects
            .select_for_update()
            .select_related("resource")
            .filter(resource=resource)
            .filter(Q(pk__in=latest_account_ids) | Q(rating_prediction__contest__in=affected_contest_ids))
            .in_bulk()
        )
        for account in accounts.values():
            final = replay.final.get(str(account.pk))
            if final is None:
                account.rating_prediction = None
                update_fields = ["rating_prediction"]
                if replay.settings.save_rating:
                    account.info = {**(account.info or {}), "rating": None}
                    account.rating_update_time = now
                    update_fields.extend(["info", "rating_update_time"])
                account.save(update_fields=update_fields)
                continue

            contest = final["contest"]
            prediction = dict(final["prediction"])
            prediction["time"] = int(min(contest.end_time, now).timestamp())
            prediction["contest"] = contest.pk
            account.rating_prediction = prediction
            update_fields = ["rating_prediction"]
            if replay.settings.save_rating:
                account.info = {**(account.info or {}), "rating": prediction["new_rating"]}
                account.rating_update_time = min(contest.end_time, now)
                update_fields.extend(["info", "rating_update_time"])
            account.save(update_fields=update_fields)

    def print_elo_mmr_top(self, replay):
        rankings = sorted(
            replay.leaderboard,
            key=lambda ranking: (-ranking["prediction"]["new_rating"], ranking["member"]),
        )
        fields = (
            "rank",
            "member",
            "old_rating",
            "new_rating",
            "rating_change",
            "rating_perf",
            "rating_sig",
            "n_contests",
        )
        table = PrettyTable(field_names=fields)
        for rank, ranking in enumerate(rankings[:20], 1):
            prediction = ranking["prediction"]
            table.add_row([rank, ranking["member"], *(prediction[field] for field in fields[2:])])
        self.stdout.write(str(table))
