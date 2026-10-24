from copy import deepcopy
from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from clist.models import Contest, Resource
from ranking.models import Account, AccountRenaming, Stage, Statistics
from ranking.utils import rename_account, update_stage


class StageScoringTest(TestCase):
    def setUp(self):
        with mock.patch.object(Resource, "update_icon"):
            self.resource = Resource.objects.create(host="stage.example", url="https://stage.example/", enable=True)
        start = timezone.now() - timedelta(days=20)
        self.season = self.contest("season", start, end=start + timedelta(days=10))
        self.rounds = [self.contest(str(i), start + timedelta(days=i + 1)) for i in range(4)]
        self.stage = Stage.objects.create(
            contest=self.season,
            score_params={
                "place": {"1": 100, "2": 75, "default": 0},
                "scoring": {"name": "general", "factor": 200},
                "order_by": ["score"],
                "fields": [{"field": "name", "safe": True}],
            },
        )
        self.team = Account.objects.create(resource=self.resource, key="team", name="Team")
        self.other = Account.objects.create(resource=self.resource, key="other", name="Other")

    def contest(self, key, start, end=None):
        return Contest.objects.create(
            resource=self.resource,
            key=key,
            title=f"Contest {key}",
            host=self.resource.host,
            url=self.resource.url + key,
            start_time=start,
            end_time=end or start + timedelta(hours=5),
        )

    def statistic(self, contest, account, solved, rank, **addition):
        return Statistics.objects.create(
            resource=self.resource,
            contest=contest,
            account=account,
            solving=solved,
            place=str(rank),
            place_as_int=rank,
            addition={"name": account.name, "out_of_competition": False, **addition},
            skip_in_stats=True,
        )

    def result(self):
        self.stage.save()
        update_stage(self.stage)
        return Statistics.objects.get(contest=self.season, account=self.team)

    def test_score_factor_is_preserved_by_default_and_can_be_disabled(self):
        self.statistic(self.rounds[0], self.other, 10, 1)
        self.statistic(self.rounds[0], self.team, 5, 2)

        assert self.result().solving == 125

        self.stage.score_params["scoring"]["use_score_factor"] = False
        assert self.result().solving == 175

    def test_filter_excludes_unofficial_scores_and_recalculates_ranks_and_team_count(self):
        self.statistic(self.rounds[0], self.other, 10, 1, out_of_competition=True)
        self.statistic(self.rounds[0], self.team, 5, 2)
        self.stage.score_params.update(
            filter_statistics={"addition__out_of_competition": False, "solving__gt": 0},
            re_ranking=True,
        )
        self.stage.score_params["scoring"]["use_score_factor"] = False

        assert self.result().solving == 300
        assert not Statistics.objects.filter(contest=self.season, account=self.other).exists()

    def set_round_ranking(self, ranking):
        self.stage.score_params["ranking_field"] = "_season_rating_ranking"
        self.stage.score_params["scoring"]["use_score_factor"] = False
        self.rounds[0].info["_season_rating_ranking"] = ranking
        self.rounds[0].save(update_fields=["info"])

    def test_external_ranking_selects_participants_and_counts_missing_results(self):
        self.statistic(self.rounds[0], self.other, 10, 1, participant_type=3)
        original = self.statistic(self.rounds[0], self.team, 5, 3)
        self.set_round_ranking({"missing-team": 1, self.team.key: 2})
        self.stage.score_params["re_ranking"] = True

        assert self.result().solving == 175
        assert not Statistics.objects.filter(contest=self.season, account=self.other).exists()
        original.refresh_from_db()
        assert original.place_as_int == 3

    def test_external_shared_places_receive_the_configured_placement_points(self):
        winner = Account.objects.create(resource=self.resource, key="winner")
        self.statistic(self.rounds[0], winner, 10, 1)
        self.statistic(self.rounds[0], self.other, 7, 3)
        self.statistic(self.rounds[0], self.team, 7, 3)
        self.set_round_ranking({winner.key: 1, self.team.key: 2, self.other.key: 2})
        self.stage.score_params["place"]["3"] = 60

        assert self.result().solving == pytest.approx(75 + 200 * 2 / 3)

    def test_missing_external_result_does_not_turn_a_gap_into_shared_points(self):
        self.statistic(self.rounds[0], self.team, 10, 1)
        self.statistic(self.rounds[0], self.other, 7, 3)
        self.set_round_ranking({self.team.key: 1, "missing-team": 2, self.other.key: 3})

        assert self.result().solving == 300

    def test_external_ranking_respects_existing_account_duplicates(self):
        alias = Account.objects.create(resource=self.resource, key="alias", duplicate=self.team)
        self.statistic(self.rounds[0], alias, 7, 3)
        self.set_round_ranking({self.team.key: 1})

        assert self.result().solving == 300

    def test_external_ranking_resolves_historical_keys_without_changing_ranks_or_field_size(self):
        original = self.statistic(self.rounds[0], self.team, 7, 5)
        ranking = {"missing-team": 1, "original-team": 2, self.team.key: 3}
        self.set_round_ranking(ranking)
        AccountRenaming.objects.create(resource=self.resource, old_key="original-team", new_key=self.team.key)

        assert self.result().solving == pytest.approx(75 + 200 * 2 / 3)
        self.rounds[0].refresh_from_db()
        assert self.rounds[0].info["_season_rating_ranking"] == ranking
        original.refresh_from_db()
        assert original.place_as_int == 5

    def test_external_ranking_resolves_duplicate_keys(self):
        alias = Account.objects.create(resource=self.resource, key="alias", duplicate=self.team)
        self.statistic(self.rounds[0], self.team, 7, 3)
        self.set_round_ranking({"missing-team": 1, alias.key: 2})

        assert self.result().solving == 175

    def test_missing_external_ranking_is_reported(self):
        self.statistic(self.rounds[0], self.team, 5, 1)
        self.stage.score_params["ranking_field"] = "_season_rating_ranking"

        with pytest.raises(ValueError, match="Missing _season_rating_ranking"):
            self.result()

    def test_empty_external_ranking_excludes_all_round_participants(self):
        self.statistic(self.rounds[0], self.team, 5, 1)
        self.set_round_ranking({})
        self.stage.save()

        update_stage(self.stage)

        assert not Statistics.objects.filter(contest=self.season).exists()

    def test_authors_receive_average_before_exponential_decay(self):
        self.stage.score_params = {
            "order_by": ["score"],
            "writers_score": "avg",
            "exponential_score_decay": 1 / 6,
        }
        self.statistic(self.rounds[0], self.team, 300, 1)
        self.statistic(self.rounds[1], self.team, 180, 1)
        for contest in self.rounds[2:]:
            contest.info["writers"] = [self.team.key]
            contest.save(update_fields=["info"])
            contest.writers.add(self.team)

        result = self.result()

        assert result.addition["problems"][str(self.rounds[2].pk)] == {"status": "A", "result": 240}
        assert result.addition["problems"][str(self.rounds[3].pk)] == {"status": "A", "result": 240}
        expected = sum((5 / 6) ** i * score / 6 for i, score in enumerate([300, 240, 240, 180]))
        assert result.solving == pytest.approx(expected)

    def test_author_credit_follows_account_merges_without_rewriting_original_writer(self):
        old = Account.objects.create(resource=self.resource, key="original-writer")
        for contest, score in zip(self.rounds[:2], (300, 180)):
            self.statistic(contest, old, score, 1)
            contest.info["_season_rating_ranking"] = {old.key: 1}
            contest.save(update_fields=["info"])
        contest = self.rounds[2]
        contest.info["writers"] = [old.key]
        contest.save(update_fields=["info"])
        contest.writers.add(old)
        rename_account(old, self.team)

        for mode, score in (("avg", 240), ("max", 300)):
            with self.subTest(mode=mode):
                self.stage.score_params = {
                    "order_by": ["score"],
                    "writers_score": mode,
                    "ranking_field": "_season_rating_ranking",
                }

                result = self.result()

                assert result.solving == 480 + score
                assert result.addition["problems"][str(contest.pk)]["result"] == score
                contest.refresh_from_db()
                assert contest.info["writers"] == [old.key]
                for round_contest in self.rounds[:2]:
                    round_contest.refresh_from_db()
                    assert round_contest.info["_season_rating_ranking"] == {old.key: 1}

    def test_author_credit_respects_existing_account_duplicates(self):
        alias = Account.objects.create(resource=self.resource, key="writer-alias", duplicate=self.team)
        self.statistic(self.rounds[0], self.team, 300, 1)
        self.statistic(self.rounds[1], self.team, 180, 1)
        contest = self.rounds[2]
        contest.info["writers"] = [alias.key]
        contest.save(update_fields=["info"])
        contest.writers.add(alias)
        self.stage.score_params = {"order_by": ["score"], "writers_score": "avg"}

        result = self.result()

        assert result.solving == 720
        assert not Statistics.objects.filter(contest=self.season, account=alias).exists()

    def test_multiple_writer_keys_resolving_to_one_account_count_once_per_round(self):
        self.statistic(self.rounds[0], self.team, 300, 1)
        contest = self.rounds[1]
        contest.info["writers"] = ["original-writer", self.team.key]
        contest.save(update_fields=["info"])
        contest.writers.add(self.team)
        AccountRenaming.objects.create(resource=self.resource, old_key="original-writer", new_key=self.team.key)
        self.stage.score_params = {"order_by": ["score"], "writers_score": "avg"}

        result = self.result()

        assert result.solving == 600
        assert result.addition["writer"] == 1

    def test_author_renamings_are_scoped_to_the_contest_resource(self):
        with mock.patch.object(Resource, "update_icon"):
            other_resource = Resource.objects.create(host="other.example", url="https://other.example/", enable=True)
        AccountRenaming.objects.create(resource=other_resource, old_key="original-writer", new_key=self.team.key)
        self.statistic(self.rounds[0], self.team, 300, 1)
        contest = self.rounds[1]
        contest.info["writers"] = ["original-writer"]
        contest.save(update_fields=["info"])
        self.stage.score_params = {"order_by": ["score"], "writers_score": "avg"}

        assert self.result().solving == 300

    def test_unrated_round_is_excluded_from_scores_and_author_average(self):
        self.stage.score_params.update(writers_score="avg", exponential_score_decay=1 / 6)
        self.statistic(self.rounds[0], self.team, 10, 1)
        self.statistic(self.rounds[1], self.team, 20, 1)
        self.rounds[1].info.update(unrated=True, writers=[self.team.key])
        self.rounds[1].save(update_fields=["info"])
        self.rounds[1].writers.add(self.team)
        self.rounds[2].info["writers"] = [self.team.key]
        self.rounds[2].save(update_fields=["info"])
        self.rounds[2].writers.add(self.team)

        result = self.result()

        assert result.addition["problems"][str(self.rounds[2].pk)]["result"] == 300
        assert "result" not in result.addition["problems"][str(self.rounds[1].pk)]
        assert result.solving == pytest.approx(300 / 6 + (5 / 6) * 300 / 6)

    def test_authors_can_receive_the_maximum_instead_of_the_average(self):
        self.stage.score_params = {"order_by": ["score"], "writers_score": "max"}
        self.statistic(self.rounds[0], self.team, 300, 1)
        self.statistic(self.rounds[1], self.team, 180, 1)
        self.rounds[2].info["writers"] = [self.team.key]
        self.rounds[2].save(update_fields=["info"])
        self.rounds[2].writers.add(self.team)

        result = self.result()

        assert result.addition["problems"][str(self.rounds[2].pk)] == {"status": "W", "result": 300}
        assert result.solving == 780

    def test_new_season_inherits_settings_from_latest_matching_season(self):
        self.season.title = "The 4th Universal Cup. Rating"
        self.season.save(update_fields=["title"])
        self.stage.score_params["scoring"]["use_score_factor"] = False
        self.stage.score_params.update(filter_statistics={"addition__out_of_competition": False}, writers_score="avg")
        self.stage.save()
        previous = self.contest("previous", self.season.start_time - timedelta(days=365))
        previous.title = "The 3rd Universal Cup. Rating"
        previous.save(update_fields=["title"])
        Stage.objects.create(contest=previous, score_params={"scoring": {"use_score_factor": True}})
        new_season = self.contest("next", self.season.start_time + timedelta(days=365))
        new_season.title = "The 5th Universal Cup. Rating"
        new_season.save(update_fields=["title"])
        expected = deepcopy(self.stage.score_params)

        call_command("inherit_stage", contest_id=new_season.pk, stdout=StringIO())

        new_season.refresh_from_db()
        assert new_season.stage.score_params == expected
