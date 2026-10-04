from django.test import TestCase
from django.utils import timezone

from events.models import Event, Participant, Team


class TeamCountryTest(TestCase):
    def setUp(self):
        self.event = Event.objects.create(name="Test event", slug="test-event", registration_deadline=timezone.now())
        self.author = Participant.objects.create(event=self.event, country=None)
        self.team = Team.objects.create(name="Test team", event=self.event, author=self.author)

    def test_empty_team_has_no_country(self):
        assert self.team.country == ""

    def test_missing_and_unknown_countries_are_ignored(self):
        for country in (None, "", "XX"):
            Participant.objects.create(event=self.event, team=self.team, country=country)
        assert self.team.country == ""

        participant = Participant.objects.create(event=self.event, team=self.team, country="BY")
        assert self.team.country == participant.country.name

    def test_most_common_known_country_is_selected(self):
        for country in (None, "BY", "PL", "BY", ""):
            participant = Participant.objects.create(event=self.event, team=self.team, country=country)
            if country == "BY":
                expected = participant.country.name
        assert self.team.country == expected
