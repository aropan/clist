from copy import deepcopy
from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from clist.models import Contest, Resource
from ranking.enums import AccountType
from ranking.management.commands.calculate_rating_prediction import (
    ABSENT_PARTICIPANT_DECAY_FIELD,
    ELO_MMR_PLAYER_STATE_FORMAT_VERSION,
    ELO_MMR_RATING_FIELDS,
    ELO_MMR_REQUIRED_SETTINGS,
    ELO_MMR_STATE_FIELD,
    apply_elo_mmr_absent_rating_cap,
    calculate_elo_mmr_replay,
    get_elo_mmr_rated_contests,
    get_elo_mmr_settings,
    get_elo_mmr_standings,
)
from ranking.models import Account, Statistics


class EloMmrRatingPredictionTest(TestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(Resource, "update_icon")
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def rating_prediction(**overrides):
        config = {
            "algorithm": "elo_mmr_py",
            "algorithm_version": "2.0.0",
            "save_rating": True,
            "system": "mmr",
            "initial_rating": 1500.0,
            "weight_limit": 0.15,
            "sig_limit": 80.0,
            "drift_per_day": 0.0,
            "noob_delay": [],
            "split_ties": False,
            "subsample_size": None,
            "subsample_bucket": 0.00001,
        }
        config.update(overrides)
        return config

    @staticmethod
    def absent_participant_decay(**overrides):
        config = {
            "score_method": "icpc_itmo_rating",
            "score_scale": 200,
            "decay_multiplier": 0.7,
            "maximum_missed_contests": 7,
        }
        config.update(overrides)
        return config

    def create_resource(self, **rating_prediction):
        return Resource.objects.create(
            host="elo-mmr.example.com",
            url="https://elo-mmr.example.com/",
            enable=True,
            rating_prediction=self.rating_prediction(**rating_prediction),
        )

    @staticmethod
    def create_contest(resource, key="contest-1", days_ago=1):
        end_time = timezone.now() - timedelta(days=days_ago)
        contest = Contest.objects.create(
            resource=resource,
            title=key,
            start_time=end_time - timedelta(hours=5),
            end_time=end_time,
            duration_in_secs=None,
            url=f"https://elo-mmr.example.com/{key}",
            host=resource.host,
            key=key,
            n_statistics=0,
        )
        return contest

    @staticmethod
    def create_statistic(contest, key, place, account_type=AccountType.USER, solving=0):
        info = {"is_member": True} if account_type == AccountType.MEMBER else {}
        account = Account.objects.create(
            resource=contest.resource,
            key=key,
            account_type=account_type,
            info=info,
        )
        statistic = Statistics.objects.create(
            resource=contest.resource,
            contest=contest,
            account=account,
            place=str(place),
            place_as_int=place,
            solving=solving,
        )
        contest.n_statistics = (contest.n_statistics or 0) + 1
        contest.save(update_fields=["n_statistics"])
        return account, statistic

    @staticmethod
    def add_statistic(contest, account, place, solving=0):
        statistic = Statistics.objects.create(
            resource=contest.resource,
            contest=contest,
            account=account,
            place=str(place),
            place_as_int=place,
            solving=solving,
        )
        contest.n_statistics = (contest.n_statistics or 0) + 1
        contest.save(update_fields=["n_statistics"])
        return statistic

    def test_account_type_is_optional_and_ties_use_rank_intervals(self):
        resource = self.create_resource()
        contest = self.create_contest(resource)
        self.create_statistic(contest, "member-a", 1, AccountType.MEMBER)
        self.create_statistic(contest, "member-b", 1, AccountType.MEMBER)
        self.create_statistic(contest, "user", 3)

        standings, _ = get_elo_mmr_standings(contest)
        assert [(low, high) for _, low, high in standings] == [(0, 1), (0, 1), (2, 2)]
        assert len(calculate_elo_mmr_replay(resource, timezone.now()).snapshots[0].rankings) == 3

        resource.rating_prediction["account_type"] = "member"
        settings = get_elo_mmr_settings(resource)
        standings, _ = get_elo_mmr_standings(contest, settings.account_type)
        assert len(standings) == 2

    def test_statistics_without_numeric_place_are_excluded(self):
        resource = self.create_resource()
        contest = self.create_contest(resource)
        self.create_statistic(contest, "user-a", 1)
        self.create_statistic(contest, "user-b", 2)
        unranked_account, _ = self.create_statistic(contest, "unranked", None)

        standings, participants = get_elo_mmr_standings(contest)
        replay = calculate_elo_mmr_replay(resource, timezone.now())

        assert str(unranked_account.pk) not in participants
        assert len(standings) == 2
        assert len(replay.snapshots[0].rankings) == 2

    def test_statistic_removed_from_rankings_clears_elo_fields(self):
        resource = self.create_resource()
        contest = self.create_contest(resource)
        accounts_statistics = [self.create_statistic(contest, f"user-{index}", index) for index in range(1, 4)]

        call_command("calculate_rating_prediction", contest=contest.pk, stdout=StringIO())
        account, statistic = accounts_statistics[-1]
        statistic.place = None
        statistic.place_as_int = None
        statistic.save(update_fields=["place", "place_as_int"])

        call_command("calculate_rating_prediction", contest=contest.pk, stdout=StringIO())

        account.refresh_from_db()
        statistic.refresh_from_db()
        assert statistic.rating_prediction is None
        assert not any(field in statistic.addition for field in ELO_MMR_RATING_FIELDS)
        assert account.rating_prediction is None
        assert account.rating is None

    def test_unknown_account_type_is_rejected(self):
        resource = self.create_resource(account_type="unknown")

        with pytest.raises(ValueError, match="unknown account_type"):
            get_elo_mmr_settings(resource)

    def test_rating_settings_are_required(self):
        resource = self.create_resource()
        for field in ELO_MMR_REQUIRED_SETTINGS:
            resource.rating_prediction = self.rating_prediction()
            resource.rating_prediction.pop(field)
            with pytest.raises(ValueError, match=field):
                get_elo_mmr_settings(resource)

    def test_sig_noob_is_left_to_library_default(self):
        resource = self.create_resource()

        settings = get_elo_mmr_settings(resource)

        assert settings.rate_kwargs == {"mu_noob": 1500.0}

    def test_absent_participant_decay_settings_are_resource_scoped_and_validated(self):
        resource = self.create_resource(absent_participant_decay=self.absent_participant_decay())

        settings = get_elo_mmr_settings(resource)

        assert settings.absent_participant_decay.score_method == "icpc_itmo_rating"
        assert settings.absent_participant_decay.score_scale == 200
        assert settings.absent_participant_decay.decay_multiplier == pytest.approx(0.7)
        assert settings.absent_participant_decay.maximum_missed_contests == 7
        assert settings.absent_participant_decay.minimum_score is None

        resource.rating_prediction["absent_participant_decay"]["minimum_score"] = 1
        assert get_elo_mmr_settings(resource).absent_participant_decay.minimum_score == 1

        invalid_values = (
            None,
            [],
            {"decay_multiplier": 0.7},
            self.absent_participant_decay(score_method="unknown"),
            self.absent_participant_decay(score_scale=0),
            self.absent_participant_decay(score_scale=float("inf")),
            self.absent_participant_decay(decay_multiplier=-0.1),
            self.absent_participant_decay(decay_multiplier=1),
            self.absent_participant_decay(maximum_missed_contests=1.5),
            self.absent_participant_decay(maximum_missed_contests=-1),
            self.absent_participant_decay(minimum_score=-1),
            {**self.absent_participant_decay(), "unknown": 1},
        )
        for value in invalid_values:
            resource.rating_prediction["absent_participant_decay"] = value
            with pytest.raises(ValueError, match="absent_participant_decay"):
                get_elo_mmr_settings(resource)

        resource.rating_prediction.update(
            absent_participant_decay=self.absent_participant_decay(),
            rating_decay=20,
        )
        with self.assertRaisesMessage(
            ValueError,
            "absent_participant_decay cannot be combined with a positive rating_decay",
        ):
            get_elo_mmr_settings(resource)

    def test_absent_participant_decay_builds_full_standings_and_applies_cutoff(self):
        resource = self.create_resource(absent_participant_decay=self.absent_participant_decay())
        first_contest = self.create_contest(resource, key="final-0", days_ago=10)
        tracked, _ = self.create_statistic(first_contest, "tracked", 1, solving=10)
        first_anchor, _ = self.create_statistic(first_contest, "first-anchor", 2, solving=5)
        second_anchor, _ = self.create_statistic(first_contest, "second-anchor", 3, solving=1)

        for index in range(1, 9):
            contest = self.create_contest(resource, key=f"final-{index}", days_ago=10 - index)
            self.add_statistic(contest, first_anchor, 1, solving=10)
            self.add_statistic(contest, second_anchor, 2, solving=5)
        return_contest = self.create_contest(resource, key="final-9", days_ago=1)
        self.add_statistic(return_contest, tracked, 1, solving=10)
        self.add_statistic(return_contest, first_anchor, 2, solving=5)

        rated_contests = get_elo_mmr_rated_contests(resource, timezone.now())
        participant = str(tracked.pk)

        assert rated_contests[0].decay_states[participant] == {"score": 200, "missed_contests": 0}
        assert rated_contests[1].decay_states[participant]["score"] == pytest.approx(140)
        assert rated_contests[1].decay_states[participant]["missed_contests"] == 1
        assert participant in rated_contests[1].synthetic_participants
        assert {entry[0]: entry[1:] for entry in rated_contests[1].full_standings}[participant] == (1, 1)
        assert participant in rated_contests[7].synthetic_participants
        assert rated_contests[7].decay_states[participant]["missed_contests"] == 7
        assert participant not in rated_contests[8].synthetic_participants
        assert participant not in {entry[0] for entry in rated_contests[8].full_standings}
        assert rated_contests[8].decay_states[participant]["missed_contests"] == 8
        assert rated_contests[9].decay_states[participant] == {"score": 200, "missed_contests": 0}
        assert participant not in rated_contests[9].synthetic_participants

    def test_optional_minimum_score_applies_an_additional_cutoff(self):
        resource = self.create_resource(
            absent_participant_decay=self.absent_participant_decay(minimum_score=141),
        )
        first_contest = self.create_contest(resource, key="final-0", days_ago=2)
        tracked, _ = self.create_statistic(first_contest, "tracked", 1, solving=10)
        anchor, _ = self.create_statistic(first_contest, "anchor", 2, solving=5)
        second_contest = self.create_contest(resource, key="final-1", days_ago=1)
        self.add_statistic(second_contest, anchor, 1, solving=10)
        self.create_statistic(second_contest, "newcomer", 2, solving=5)

        rated_contests = get_elo_mmr_rated_contests(resource, timezone.now())

        assert rated_contests[1].decay_states[str(tracked.pk)]["score"] == pytest.approx(140)
        assert str(tracked.pk) not in rated_contests[1].synthetic_participants

    def test_zero_solving_uses_rank_only_fallback_without_division_by_zero(self):
        resource = self.create_resource(absent_participant_decay=self.absent_participant_decay())
        contest = self.create_contest(resource)
        accounts = [self.create_statistic(contest, f"user-{index}", index)[0] for index in range(1, 3)]

        (rated_contest,) = get_elo_mmr_rated_contests(resource, timezone.now())

        assert rated_contest.full_standings == [
            (str(accounts[0].pk), 0, 0),
            (str(accounts[1].pk), 1, 1),
        ]
        assert rated_contest.decay_states == {
            str(accounts[0].pk): {"score": 200, "missed_contests": 0},
            str(accounts[1].pk): {"score": 100, "missed_contests": 0},
        }

    def test_absent_rating_cap_translates_the_complete_player_state(self):
        previous_player = {
            "normal_factor": {"mu": 500.0},
            "approx_posterior": {"mu": 100.0},
            "logistic_factors": [{"mu": 200.0}],
            "event_history": [{"rating_mu": 100}],
        }
        increased_player = {
            "normal_factor": {"mu": 520.0},
            "approx_posterior": {"mu": 119.5},
            "logistic_factors": [{"mu": 220.0}],
            "event_history": [{"rating_mu": 100}, {"rating_mu": 120}],
        }
        checkpoint = {"players": {"tracked": increased_player}}

        assert apply_elo_mmr_absent_rating_cap(checkpoint, {"tracked": previous_player}, {"tracked"})
        assert increased_player["event_history"][-1]["rating_mu"] == 100
        assert increased_player["approx_posterior"]["mu"] == 100
        assert increased_player["normal_factor"]["mu"] == pytest.approx(500.5)
        assert increased_player["logistic_factors"][0]["mu"] == pytest.approx(200.5)

        decreased_player = deepcopy(increased_player)
        decreased_player["event_history"][-1]["rating_mu"] = 90
        decreased_player["approx_posterior"]["mu"] = 90
        checkpoint = {"players": {"tracked": decreased_player}}
        assert not apply_elo_mmr_absent_rating_cap(checkpoint, {"tracked": previous_player}, {"tracked"})
        assert decreased_player["approx_posterior"]["mu"] == 90

    def test_prediction_is_mirrored_to_actual_rating_for_members(self):
        resource = self.create_resource(account_type="member")
        contest = self.create_contest(resource)
        first_account, first_statistic = self.create_statistic(contest, "member-a", 1, AccountType.MEMBER)
        second_account, second_statistic = self.create_statistic(contest, "member-b", 2, AccountType.MEMBER)
        user_account, user_statistic = self.create_statistic(contest, "user", 3)
        Account.objects.filter(pk=first_account.pk).update(resource_rank=10)

        call_command("calculate_rating_prediction", contest=contest.pk, stdout=StringIO())

        for account, statistic in ((first_account, first_statistic), (second_account, second_statistic)):
            account.refresh_from_db()
            statistic.refresh_from_db()
            assert statistic.rating_prediction
            assert account.rating_prediction
            assert ELO_MMR_STATE_FIELD in statistic.rating_prediction
            assert ELO_MMR_STATE_FIELD not in account.rating_prediction
            for field in ELO_MMR_RATING_FIELDS:
                assert statistic.addition[field] == statistic.rating_prediction[field]
            assert account.rating == statistic.rating_prediction["new_rating"]
            assert account.rating50 == int(account.rating / 50)
            assert account.resource_rank == (10 if account.pk == first_account.pk else None)
            assert account.info["rating"] == account.rating

        user_account.refresh_from_db()
        user_statistic.refresh_from_db()
        assert user_account.rating is None
        assert user_account.rating_prediction is None
        assert user_statistic.rating_prediction is None
        assert not any(field in user_statistic.addition for field in ELO_MMR_RATING_FIELDS)

        contest.refresh_from_db()
        resource.refresh_from_db()
        assert contest.is_rated is True
        assert resource.rating_update_time is not None
        assert contest.info["_rating_calculation"]["algorithm"] == "elo_mmr_py"
        standings = contest.info["standings"]
        member_fields = standings["account_type_fields"]["member"]["fixed_fields"]
        assert set(ELO_MMR_RATING_FIELDS) <= set(member_fields)
        assert not set(ELO_MMR_RATING_FIELDS) & set(standings.get("fixed_fields", []))

    def test_save_rating_false_keeps_prediction_only(self):
        resource = self.create_resource(save_rating=False)
        contest = self.create_contest(resource)
        account, statistic = self.create_statistic(contest, "user-a", 1)
        self.create_statistic(contest, "user-b", 2)

        call_command("calculate_rating_prediction", contest=contest.pk, stdout=StringIO())

        account.refresh_from_db()
        statistic.refresh_from_db()
        assert account.rating_prediction
        assert statistic.rating_prediction
        assert account.rating is None
        assert not any(field in statistic.addition for field in ELO_MMR_RATING_FIELDS)

    def create_decay_history(self, resource):
        contests = [
            self.create_contest(resource, key=f"final-{index}", days_ago=(5 - index) * 365) for index in range(4)
        ]
        first, _ = self.create_statistic(contests[0], "university:first", 1, AccountType.UNIVERSITY)
        second, _ = self.create_statistic(contests[0], "university:second", 2, AccountType.UNIVERSITY)
        third, _ = self.create_statistic(contests[1], "university:third", 2, AccountType.UNIVERSITY)
        for contest, accounts in (
            (contests[1], (second,)),
            (contests[2], (second, third)),
            (contests[3], (first, second)),
        ):
            for place, account in enumerate(accounts, start=1):
                Statistics.objects.create(
                    resource=resource, contest=contest, account=account, place=str(place), place_as_int=place
                )
            contest.n_statistics = 2
            contest.save(update_fields=["n_statistics"])
        return contests, (first, second, third)

    def test_decay_only_reduces_inactive_account_rating(self):
        resource = self.create_resource(account_type="university", rating_decay=50)
        contests, (first, second, third) = self.create_decay_history(resource)
        statistic_ids = set(Statistics.objects.filter(resource=resource).values_list("pk", flat=True))

        call_command("calculate_rating_prediction", contest=contests[-1].pk, stdout=StringIO())

        first_result = Statistics.objects.get(contest=contests[0], account=first)
        returned_result = Statistics.objects.get(contest=contests[-1], account=first)
        assert returned_result.addition["old_rating"] == first_result.addition["new_rating"]
        assert returned_result.rating_prediction["n_contests"] == 2
        assert returned_result.rating_prediction[ELO_MMR_STATE_FIELD]["player_state"]["type"] == "delta"
        for account in (first, second, third):
            account.refresh_from_db()
            last_result = Statistics.objects.filter(account=account).order_by("-contest__start_time").first()
            decay = 50 if account == third else 0
            assert account.rating == last_result.addition["new_rating"] - decay
            assert account.rating_prediction["rating_decay"] == decay
            assert account.rating_prediction["contest"] == last_result.contest_id
            assert account.rating_prediction["time"] == int(contests[-1].end_time.timestamp())
            assert account.rating_update_time == contests[-1].end_time
            assert account.rating_prediction["new_rating"] == (
                account.rating_prediction["old_rating"] + account.rating_prediction["rating_change"]
            )
        assert set(Statistics.objects.filter(resource=resource).values_list("pk", flat=True)) == statistic_ids

        with mock.patch(
            "ranking.management.commands.calculate_rating_prediction.Command.save_elo_mmr_accounts"
        ) as save_accounts:
            call_command("calculate_rating_prediction", contest=contests[-1].pk, stdout=StringIO())
        save_accounts.assert_not_called()

    def test_changing_or_disabling_decay_replays_the_entire_history(self):
        resource = self.create_resource(account_type="university")
        contests, accounts = self.create_decay_history(resource)
        call_command("calculate_rating_prediction", contest=contests[0].pk, stdout=StringIO())
        original = dict(Account.objects.filter(pk__in=[a.pk for a in accounts]).values_list("pk", "rating"))

        for decay in (50, 25, 0):
            resource.rating_prediction["rating_decay"] = decay
            resource.save(update_fields=["rating_prediction"])
            replay = calculate_elo_mmr_replay(resource, timezone.now(), start_time=contests[-1].start_time)
            assert len(replay.snapshots) == len(contests)
            call_command("calculate_rating_prediction", contest=contests[-1].pk, stdout=StringIO())
            actual = dict(Account.objects.filter(pk__in=[a.pk for a in accounts]).values_list("pk", "rating"))
            assert actual == {int(key): final["prediction"]["new_rating"] for key, final in replay.final.items()}
        assert actual == original

    def test_decay_starts_only_after_first_participation(self):
        resource = self.create_resource(account_type="university", rating_decay=50)
        contests, _ = self.create_decay_history(resource)
        late_account, debut = self.create_statistic(contests[2], "university:late", 3, AccountType.UNIVERSITY)
        never_participated = Account.objects.create(
            resource=resource, key="university:never", account_type=AccountType.UNIVERSITY
        )

        earlier = calculate_elo_mmr_replay(resource, now=contests[1].end_time + timedelta(hours=1))
        assert str(late_account.pk) not in earlier.final
        assert str(never_participated.pk) not in earlier.final

        call_command("calculate_rating_prediction", contest=contests[-1].pk, stdout=StringIO())

        late_account.refresh_from_db()
        debut.refresh_from_db()
        never_participated.refresh_from_db()
        assert debut.addition["old_rating"] == resource.rating_prediction["initial_rating"]
        assert debut.rating_prediction["n_contests"] == 1
        assert late_account.rating == debut.addition["new_rating"] - 50
        assert late_account.rating_prediction["rating_decay"] == 50
        assert Statistics.objects.filter(account=late_account).count() == 1
        assert never_participated.rating is None
        assert never_participated.rating_prediction is None
        assert not Statistics.objects.filter(account=never_participated).exists()

    def test_decay_stops_at_zero_and_returning_account_uses_last_competitive_rating(self):
        resource = self.create_resource(account_type="university", rating_decay=2000)
        contests, (first, _, _) = self.create_decay_history(resource)
        before_return = calculate_elo_mmr_replay(resource, now=contests[2].end_time + timedelta(hours=1))
        first_rating = before_return.snapshots[0].rankings[0]["prediction"]["new_rating"]
        assert before_return.final[str(first.pk)]["prediction"]["new_rating"] == 0
        assert before_return.final[str(first.pk)]["prediction"]["rating_decay"] == first_rating

        call_command("calculate_rating_prediction", contest=contests[-1].pk, stdout=StringIO())

        returned = Statistics.objects.get(account=first, contest=contests[-1])
        assert returned.addition["old_rating"] == first_rating
        assert returned.addition["new_rating"] > 0
        assert Statistics.objects.get(account=first, contest=contests[0]).addition["new_rating"] == first_rating
        assert not Account.objects.filter(resource=resource, rating__lt=0).exists()
        assert Statistics.objects.filter(resource=resource).count() == 8

    def test_rating_with_decay_is_not_negative_after_participation(self):
        resource = self.create_resource(initial_rating=0, rating_decay=20)
        contest = self.create_contest(resource)
        self.create_statistic(contest, "winner", 1)
        account, statistic = self.create_statistic(contest, "loser", 2)

        call_command("calculate_rating_prediction", contest=contest.pk, stdout=StringIO())

        statistic.refresh_from_db()
        account.refresh_from_db()
        assert account.rating == statistic.addition["new_rating"] == 0
        assert statistic.rating_prediction["rating_perf"] < 0
        player = statistic.rating_prediction[ELO_MMR_STATE_FIELD]["player_state"]["player"]
        assert player["approx_posterior"]["mu"] == 0
        assert player["event_history"][-1]["rating_mu"] == 0

    def test_invalidating_final_undoes_its_decay_without_creating_statistics(self):
        resource = self.create_resource(account_type="university", rating_decay=50)
        contests, (_, _, third) = self.create_decay_history(resource)
        call_command("calculate_rating_prediction", contest=contests[0].pk, stdout=StringIO())
        third.refresh_from_db()
        decayed_rating = third.rating

        Statistics.objects.filter(contest=contests[-1]).update(skip_in_stats=True)
        call_command("calculate_rating_prediction", contest=contests[-1].pk, stdout=StringIO())

        third.refresh_from_db()
        assert third.rating == decayed_rating + 50
        assert third.rating_prediction["rating_decay"] == 0
        assert third.rating_update_time == contests[-2].end_time
        assert Statistics.objects.filter(resource=resource).count() == 8

    def test_invalid_rating_decay_is_rejected(self):
        resource = self.create_resource()
        for value in (-1, float("inf"), float("nan"), None, "50"):
            resource.rating_prediction["rating_decay"] = value
            with self.assertRaisesMessage(ValueError, "rating_decay must be a finite non-negative number"):
                get_elo_mmr_settings(resource)

    def create_absent_participant_history(self):
        resource = self.create_resource(absent_participant_decay=self.absent_participant_decay())
        first_contest = self.create_contest(resource, key="final-1", days_ago=10)
        first_anchor, _ = self.create_statistic(first_contest, "first-anchor", 1, solving=10)
        second_anchor, _ = self.create_statistic(first_contest, "second-anchor", 2, solving=5)
        tracked, tracked_statistic = self.create_statistic(first_contest, "tracked", 3, solving=1)
        call_command("calculate_rating_prediction", contest=first_contest.pk, stdout=StringIO())

        second_contest = self.create_contest(resource, key="final-2", days_ago=9)
        self.add_statistic(second_contest, first_anchor, 1, solving=0)
        self.add_statistic(second_contest, second_anchor, 2, solving=0)
        tracked_statistic.refresh_from_db()
        return resource, (first_anchor, second_anchor, tracked), (first_contest, second_contest), tracked_statistic

    def test_synthetic_participant_updates_only_the_account(self):
        resource, _, (first_contest, second_contest), tracked_statistic = self.create_absent_participant_history()
        statistic_ids = list(Statistics.objects.filter(resource=resource).order_by("pk").values_list("pk", flat=True))
        tracked_prediction = deepcopy(tracked_statistic.rating_prediction)
        tracked_addition = deepcopy(tracked_statistic.addition)

        call_command("calculate_rating_prediction", contest=second_contest.pk, stdout=StringIO())

        tracked_statistic.refresh_from_db()
        tracked = tracked_statistic.account
        tracked.refresh_from_db()
        state = tracked.rating_prediction[ABSENT_PARTICIPANT_DECAY_FIELD]
        assert state["score"] == pytest.approx(200 * (1 / 3) * (1 / 10) * 0.7)
        assert state["missed_contests"] == 1
        assert tracked.rating_prediction["contest"] == first_contest.pk
        assert tracked.rating_prediction["time"] == int(second_contest.end_time.timestamp())
        assert tracked.rating == tracked.rating_prediction["new_rating"]
        assert tracked.rating <= tracked_prediction["new_rating"]
        assert tracked.rating_prediction["rating_change"] <= 0
        assert tracked_statistic.rating_prediction == tracked_prediction
        assert tracked_statistic.addition == tracked_addition
        assert list(Statistics.objects.filter(resource=resource).order_by("pk").values_list("pk", flat=True)) == (
            statistic_ids
        )
        assert ABSENT_PARTICIPANT_DECAY_FIELD not in tracked_statistic.rating_prediction
        second_contest.refresh_from_db()
        assert ABSENT_PARTICIPANT_DECAY_FIELD not in second_contest.rating_prediction_fields.get("types", {})

    def test_cutoff_keeps_private_state_and_return_resets_it(self):
        resource, (first_anchor, second_anchor, tracked), contests, _ = self.create_absent_participant_history()
        for index in range(2, 9):
            contest = self.create_contest(resource, key=f"final-{index + 1}", days_ago=9 - index)
            self.add_statistic(contest, first_anchor, 1, solving=10)
            self.add_statistic(contest, second_anchor, 2, solving=5)
            contests += (contest,)

        call_command("calculate_rating_prediction", contest=contests[-1].pk, stdout=StringIO())

        tracked.refresh_from_db()
        state = tracked.rating_prediction[ABSENT_PARTICIPANT_DECAY_FIELD]
        assert state["missed_contests"] == 8
        assert state["score"] == pytest.approx(200 * (1 / 3) * (1 / 10) * 0.7**8)
        assert tracked.rating_prediction["time"] == int(contests[-2].end_time.timestamp())
        cutoff_rating = tracked.rating

        return_contest = self.create_contest(resource, key="final-return", days_ago=1)
        returned = self.add_statistic(return_contest, tracked, 1, solving=10)
        self.add_statistic(return_contest, first_anchor, 2, solving=5)
        call_command("calculate_rating_prediction", contest=return_contest.pk, stdout=StringIO())

        tracked.refresh_from_db()
        returned.refresh_from_db()
        assert tracked.rating_prediction[ABSENT_PARTICIPANT_DECAY_FIELD] == {"score": 200.0, "missed_contests": 0}
        assert returned.rating_prediction["old_rating"] == cutoff_rating
        assert ABSENT_PARTICIPANT_DECAY_FIELD not in returned.rating_prediction

    def test_disabling_absent_decay_clears_private_state_and_replays_history(self):
        resource, _, (first_contest, second_contest), tracked_statistic = self.create_absent_participant_history()
        call_command("calculate_rating_prediction", contest=second_contest.pk, stdout=StringIO())
        tracked = tracked_statistic.account
        tracked.refresh_from_db()
        assert ABSENT_PARTICIPANT_DECAY_FIELD in tracked.rating_prediction

        resource.rating_prediction.pop("absent_participant_decay")
        resource.save(update_fields=["rating_prediction"])
        replay = calculate_elo_mmr_replay(resource, timezone.now(), start_time=second_contest.start_time)
        assert len(replay.snapshots) == 2
        call_command("calculate_rating_prediction", contest=second_contest.pk, stdout=StringIO())

        tracked.refresh_from_db()
        tracked_statistic.refresh_from_db()
        assert ABSENT_PARTICIPANT_DECAY_FIELD not in tracked.rating_prediction
        assert tracked.rating_prediction["contest"] == first_contest.pk
        assert tracked.rating_prediction["time"] == int(first_contest.end_time.timestamp())
        assert tracked.rating == tracked_statistic.rating_prediction["new_rating"]

    def test_absent_decay_hash_includes_solving_and_configuration(self):
        resource, _, (_, second_contest), tracked_statistic = self.create_absent_participant_history()
        call_command("calculate_rating_prediction", contest=second_contest.pk, stdout=StringIO())
        second_contest.refresh_from_db()
        original_hash = second_contest.rating_prediction_hash

        tracked_statistic.solving = 2
        tracked_statistic.save(update_fields=["solving"])
        replay = calculate_elo_mmr_replay(resource, timezone.now(), start_time=second_contest.start_time)
        assert len(replay.snapshots) == 2
        assert replay.snapshots[-1].input_hash != original_hash

        solving_hash = replay.snapshots[-1].input_hash
        resource.rating_prediction["absent_participant_decay"]["decay_multiplier"] = 0.6
        replay = calculate_elo_mmr_replay(resource, timezone.now(), start_time=second_contest.start_time)
        assert len(replay.snapshots) == 2
        assert replay.snapshots[-1].input_hash != solving_hash

    def test_reparse_of_old_contest_recalculates_later_contests(self):
        resource = self.create_resource()
        first_contest = self.create_contest(resource, key="contest-1", days_ago=10)
        second_contest = self.create_contest(resource, key="contest-2", days_ago=1)
        first_account, first_statistic = self.create_statistic(first_contest, "user-a", 1)
        second_account, second_statistic = self.create_statistic(first_contest, "user-b", 2)
        for account, place in ((first_account, 1), (second_account, 2)):
            Statistics.objects.create(
                resource=resource,
                contest=second_contest,
                account=account,
                place=str(place),
                place_as_int=place,
            )
        second_contest.n_statistics = 2
        second_contest.save(update_fields=["n_statistics"])

        call_command("calculate_rating_prediction", contest=first_contest.pk, stdout=StringIO())
        second_contest.refresh_from_db()
        previous_hash = second_contest.rating_prediction_hash

        first_statistic.place = "2"
        first_statistic.place_as_int = 2
        first_statistic.save(update_fields=["place", "place_as_int"])
        second_statistic.place = "1"
        second_statistic.place_as_int = 1
        second_statistic.save(update_fields=["place", "place_as_int"])
        call_command("calculate_rating_prediction", contest=first_contest.pk, stdout=StringIO())

        second_contest.refresh_from_db()
        assert second_contest.rating_prediction_hash != previous_hash
        rating_prediction_timing = second_contest.rating_prediction_timing

        call_command("calculate_rating_prediction", contest=first_contest.pk, stdout=StringIO())
        second_contest.refresh_from_db()
        assert second_contest.rating_prediction_timing == rating_prediction_timing

    def test_suffix_replay_restores_checkpoint_from_statistics(self):
        resource = self.create_resource()
        first_contest = self.create_contest(resource, key="contest-1", days_ago=10)
        second_contest = self.create_contest(resource, key="contest-2", days_ago=1)
        accounts = [
            self.create_statistic(first_contest, "user-a", 1)[0],
            self.create_statistic(first_contest, "user-b", 2)[0],
        ]
        for account, place in zip(accounts, (2, 1)):
            Statistics.objects.create(
                resource=resource,
                contest=second_contest,
                account=account,
                place=str(place),
                place_as_int=place,
            )
        second_contest.n_statistics = 2
        second_contest.save(update_fields=["n_statistics"])

        call_command("calculate_rating_prediction", contest=first_contest.pk, stdout=StringIO())
        expected = {
            statistic.account_id: statistic.rating_prediction
            for statistic in Statistics.objects.filter(contest=second_contest)
        }

        replay = calculate_elo_mmr_replay(resource, timezone.now(), start_time=second_contest.start_time)

        assert [snapshot.contest.pk for snapshot in replay.snapshots] == [second_contest.pk]
        assert {ranking["account_id"]: ranking["prediction"] for ranking in replay.snapshots[0].rankings} == expected

    def test_statistic_checkpoint_stores_only_current_player_delta(self):
        resource = self.create_resource()
        contests = [self.create_contest(resource, key=f"contest-{index}", days_ago=5 - index) for index in range(1, 5)]
        accounts = [
            self.create_statistic(contests[0], "user-a", 1)[0],
            self.create_statistic(contests[0], "user-b", 2)[0],
        ]
        for contest_index, contest in enumerate(contests[1:], start=1):
            for account, place in zip(accounts, (2, 1) if contest_index % 2 else (1, 2)):
                Statistics.objects.create(
                    resource=resource,
                    contest=contest,
                    account=account,
                    place=str(place),
                    place_as_int=place,
                )
            contest.n_statistics = 2
            contest.save(update_fields=["n_statistics"])

        call_command("calculate_rating_prediction", contest=contests[0].pk, stdout=StringIO())

        for account in accounts:
            statistics = Statistics.objects.filter(account=account).order_by("contest__start_time", "contest_id")
            for index, statistic in enumerate(statistics, start=1):
                state = statistic.rating_prediction[ELO_MMR_STATE_FIELD]
                assert state["player_state_format_version"] == ELO_MMR_PLAYER_STATE_FORMAT_VERSION
                stored_player_state = state["player_state"]
                assert stored_player_state["type"] == ("full" if index == 1 else "delta")
                if index > 1:
                    assert "player" not in stored_player_state
                    assert isinstance(stored_player_state["event"], dict)
                    assert isinstance(stored_player_state["logistic_factor"], dict)
                    assert "event_history" not in stored_player_state
                    assert "logistic_factors" not in stored_player_state
                assert statistic.rating_prediction["n_contests"] == index

        expected = {
            statistic.account_id: statistic.rating_prediction
            for statistic in Statistics.objects.filter(contest=contests[-1])
        }
        replay = calculate_elo_mmr_replay(resource, timezone.now(), start_time=contests[-1].start_time)
        assert [snapshot.contest.pk for snapshot in replay.snapshots] == [contests[-1].pk]
        assert {ranking["account_id"]: ranking["prediction"] for ranking in replay.snapshots[0].rankings} == expected

    def test_suffix_replay_rolls_back_account_removed_from_contest(self):
        resource = self.create_resource()
        first_contest = self.create_contest(resource, key="contest-1", days_ago=10)
        second_contest = self.create_contest(resource, key="contest-2", days_ago=1)
        accounts_statistics = [self.create_statistic(first_contest, f"user-{index}", index) for index in range(1, 4)]
        second_statistics = []
        for account, place in zip((item[0] for item in accounts_statistics), (3, 2, 1)):
            second_statistics.append(
                Statistics.objects.create(
                    resource=resource,
                    contest=second_contest,
                    account=account,
                    place=str(place),
                    place_as_int=place,
                )
            )
        second_contest.n_statistics = 3
        second_contest.save(update_fields=["n_statistics"])

        call_command("calculate_rating_prediction", contest=first_contest.pk, stdout=StringIO())
        removed_account, first_statistic = accounts_statistics[-1]
        second_statistics[-1].delete()

        call_command("calculate_rating_prediction", contest=second_contest.pk, stdout=StringIO())

        removed_account.refresh_from_db()
        first_statistic.refresh_from_db()
        assert removed_account.rating_prediction["contest"] == first_contest.pk
        assert removed_account.rating_prediction["new_rating"] == first_statistic.rating_prediction["new_rating"]
        assert removed_account.rating == first_statistic.rating_prediction["new_rating"]

        first_statistic.delete()
        call_command("calculate_rating_prediction", contest=first_contest.pk, stdout=StringIO())

        removed_account.refresh_from_db()
        assert removed_account.rating_prediction is None
        assert removed_account.rating is None
        assert removed_account.rating50 is None

    def test_suffix_replay_invalidates_contest_with_too_few_rankings(self):
        resource = self.create_resource()
        first_contest = self.create_contest(resource, key="contest-1", days_ago=10)
        second_contest = self.create_contest(resource, key="contest-2", days_ago=1)
        accounts_statistics = [self.create_statistic(first_contest, f"user-{index}", index) for index in range(1, 4)]
        second_statistics = []
        for account, place in zip((item[0] for item in accounts_statistics), (3, 2, 1)):
            second_statistics.append(
                Statistics.objects.create(
                    resource=resource,
                    contest=second_contest,
                    account=account,
                    place=str(place),
                    place_as_int=place,
                )
            )
        second_contest.n_statistics = 3
        second_contest.save(update_fields=["n_statistics"])
        call_command("calculate_rating_prediction", contest=first_contest.pk, stdout=StringIO())

        for statistic in second_statistics[1:]:
            statistic.place = None
            statistic.place_as_int = None
            statistic.save(update_fields=["place", "place_as_int"])
        call_command("calculate_rating_prediction", contest=second_contest.pk, stdout=StringIO())

        second_contest.refresh_from_db()
        assert second_contest.rating_prediction_hash is None
        assert second_contest.is_rated is False
        assert "_rating_calculation" not in second_contest.info
        for (account, first_statistic), second_statistic in zip(accounts_statistics, second_statistics):
            account.refresh_from_db()
            first_statistic.refresh_from_db()
            second_statistic.refresh_from_db()
            assert second_statistic.rating_prediction is None
            assert not any(field in second_statistic.addition for field in ELO_MMR_RATING_FIELDS)
            assert account.rating_prediction["contest"] == first_contest.pk
            assert account.rating == first_statistic.rating_prediction["new_rating"]

    def test_suffix_replay_rejects_incompatible_statistic_checkpoint(self):
        resource = self.create_resource()
        first_contest = self.create_contest(resource, key="contest-1", days_ago=10)
        second_contest = self.create_contest(resource, key="contest-2", days_ago=1)
        accounts_statistics = [
            self.create_statistic(first_contest, "user-a", 1),
            self.create_statistic(first_contest, "user-b", 2),
        ]
        for account, place in ((accounts_statistics[0][0], 1), (accounts_statistics[1][0], 2)):
            Statistics.objects.create(
                resource=resource,
                contest=second_contest,
                account=account,
                place=str(place),
                place_as_int=place,
            )
        second_contest.n_statistics = 2
        second_contest.save(update_fields=["n_statistics"])
        call_command("calculate_rating_prediction", contest=first_contest.pk, stdout=StringIO())

        statistic = accounts_statistics[0][1]
        statistic.refresh_from_db()
        statistic.rating_prediction[ELO_MMR_STATE_FIELD]["algorithm_version"] = "1.0.0"
        statistic.save(update_fields=["rating_prediction"])

        with pytest.raises(ValueError, match="statistic checkpoint algorithm_version"):
            call_command("calculate_rating_prediction", contest=second_contest.pk, stdout=StringIO())

    def test_dryrun_does_not_write(self):
        resource = self.create_resource()
        contest = self.create_contest(resource)
        account, statistic = self.create_statistic(contest, "user-a", 1)
        self.create_statistic(contest, "user-b", 2)

        output = StringIO()
        call_command("calculate_rating_prediction", contest=contest.pk, dryrun=True, stdout=output)

        account.refresh_from_db()
        statistic.refresh_from_db()
        contest.refresh_from_db()
        assert "rating_sig" in output.getvalue()
        assert account.rating_prediction is None
        assert statistic.rating_prediction is None
        assert contest.rating_prediction_hash is None

    def test_legacy_rating_prediction_still_uses_existing_algorithm(self):
        resource = Resource.objects.create(
            host="legacy-rating.example.com",
            url="https://legacy-rating.example.com/",
            enable=True,
            rating_prediction={"initial_rating": 1500},
        )
        contest = self.create_contest(resource)
        account, statistic = self.create_statistic(contest, "user-a", 1)
        self.create_statistic(contest, "user-b", 2)

        call_command("calculate_rating_prediction", contest=contest.pk, stdout=StringIO())

        account.refresh_from_db()
        statistic.refresh_from_db()
        assert account.rating_prediction
        assert statistic.rating_prediction
        assert account.rating is None

    def test_legacy_resource_requires_contest_selector(self):
        resource = Resource.objects.create(
            host="legacy-resource.example.com",
            url="https://legacy-resource.example.com/",
            enable=True,
            rating_prediction={"initial_rating": 1500},
        )
        contest = self.create_contest(resource)
        account, statistic = self.create_statistic(contest, "user-a", 1)
        self.create_statistic(contest, "user-b", 2)

        call_command("calculate_rating_prediction", resources=[resource.host], stdout=StringIO())

        account.refresh_from_db()
        statistic.refresh_from_db()
        contest.refresh_from_db()
        assert account.rating_prediction is None
        assert statistic.rating_prediction is None
        assert contest.rating_prediction_hash is None
