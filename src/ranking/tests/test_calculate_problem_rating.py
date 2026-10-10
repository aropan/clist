from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from clist.models import Contest, Problem, Resource
from logify.models import EventLog, EventStatus
from ranking.models import Account, Statistics


class CalculateProblemRatingTest(TestCase):
    def setUp(self):
        with mock.patch.object(Resource, "update_icon"):
            self.resource = Resource.objects.create(
                host="problem-rating.example.com",
                url="https://problem-rating.example.com/",
                enable=True,
                has_problem_rating=True,
                avg_rating=None,
            )
        end_time = timezone.now() - timedelta(days=1)
        self.contest = Contest.objects.create(
            resource=self.resource,
            title="Missing ratings",
            key="1",
            host=self.resource.host,
            url=self.resource.url + "contest/1",
            start_time=end_time - timedelta(hours=2),
            end_time=end_time,
            info={"problems": [{"short": "A", "name": "Task A", "rating": 1800}]},
        )
        self.problem = Problem.objects.create(
            resource=self.resource, contest=self.contest, key="A", name="Task A", short="A", rating=1800
        )
        self.problem.contests.add(self.contest)

    def add_statistic(self, key, place, old_rating=None, **addition):
        account = Account.objects.create(resource=self.resource, key=key)
        if old_rating is not None:
            addition["old_rating"] = old_rating
        addition.setdefault("problems", {"A": {"result": "+" if place == 1 else "-1"}})
        return Statistics.objects.create(
            resource=self.resource,
            contest=self.contest,
            account=account,
            place=str(place),
            place_as_int=place,
            addition=addition,
        )

    def calculate(self, force=True, **options):
        call_command("calculate_problem_rating", contest=self.contest.pk, force=force, stdout=StringIO(), **options)
        self.problem.refresh_from_db()
        self.contest.refresh_from_db()

    def test_missing_participant_rating_does_not_break_calculation(self):
        self.add_statistic("rated", 1, old_rating=1600)
        self.add_statistic("unrated", 2)

        self.calculate()

        assert isinstance(self.problem.rating, int)
        assert self.contest.problem_rating_hash
        assert EventLog.objects.get(name="calculate_problem_rating").status == EventStatus.COMPLETED

    def test_missing_rating_backfill_invalidates_hash(self):
        self.add_statistic("rated", 1, old_rating=1600)
        unrated = self.add_statistic("unrated", 2)
        self.calculate(force=False)
        original_hash = self.contest.problem_rating_hash
        original_rating = self.problem.rating

        unrated.addition["old_rating"] = 2600
        unrated.save(update_fields=["addition"])
        self.calculate(force=False)
        ordinary_rating = self.problem.rating

        assert self.contest.problem_rating_hash != original_hash
        assert ordinary_rating != original_rating
        assert EventLog.objects.filter(name="calculate_problem_rating").latest("pk").status == EventStatus.COMPLETED
        self.calculate()
        assert self.problem.rating == ordinary_rating

    def test_changed_rating_invalidates_hash(self):
        rated = self.add_statistic("rated", 1, old_rating=1600)
        self.calculate(force=False)
        original_hash = self.contest.problem_rating_hash
        original_rating = self.problem.rating

        rated.addition["old_rating"] = 2600
        rated.save(update_fields=["addition"])
        self.calculate(force=False)

        assert self.contest.problem_rating_hash != original_hash
        assert self.problem.rating != original_rating

    def test_unchanged_ratings_reuse_hash(self):
        self.add_statistic("rated", 1, old_rating=1600)
        self.add_statistic("unrated", 2)
        self.calculate(force=False)
        original_hash = self.contest.problem_rating_hash
        original_rating = self.problem.rating

        self.calculate(force=False)

        event = EventLog.objects.filter(name="calculate_problem_rating").latest("pk")
        assert event.status == EventStatus.SKIPPED
        assert event.message == "unchanged hash"
        assert self.contest.problem_rating_hash == original_hash
        assert self.problem.rating == original_rating

    def test_contest_without_ratings_keeps_existing_problem_rating(self):
        self.add_statistic("unrated", 1)

        self.calculate()

        assert self.problem.rating == 1800
        assert self.contest.info["problems"][0]["rating"] == 1800
        event = EventLog.objects.get(name="calculate_problem_rating")
        assert event.status == EventStatus.SKIPPED
        assert event.message == "no participant ratings"

    def test_zero_rating_is_valid(self):
        self.add_statistic("rated-zero", 1, old_rating=0)

        self.calculate()

        assert self.contest.problem_rating_hash
        assert EventLog.objects.get(name="calculate_problem_rating").status == EventStatus.COMPLETED

    def test_team_member_without_rating_is_skipped(self):
        self.add_statistic("rated", 1, old_rating=1600)
        self.add_statistic("team", 2, team_id="team", _members=[{"account": "unrated"}])
        Account.objects.create(resource=self.resource, key="unrated")

        self.calculate()

        assert isinstance(self.problem.rating, int)
        assert self.contest.problem_rating_hash

    def test_ignored_missing_team_member_without_average_rating_is_skipped(self):
        self.add_statistic("rated", 1, old_rating=1600)
        self.add_statistic("team", 2, team_id="team", _members=[{"account": "missing"}])

        self.calculate(ignore_missing_account=True)

        assert isinstance(self.problem.rating, int)
        assert self.contest.problem_rating_hash
