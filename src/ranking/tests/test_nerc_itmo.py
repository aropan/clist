from datetime import UTC, datetime
from unittest import mock

from django.test import SimpleTestCase

from ranking.management.modules.nerc_itmo import Statistic


class NercItmoStandingsTest(SimpleTestCase):
    def test_unrecognized_medal_text_uses_medal_specific_field(self):
        html = """
        <table class="standings">
            <tr><th>Place</th><th>Name</th><th>Medal</th></tr>
            <tr><td>1</td><td>Alpha</td><td>G extra</td></tr>
        </table>
        """
        parser = Statistic(
            name="Test",
            standings_url="https://example.com/standings.html",
            start_time=datetime(2026, 9, 1, tzinfo=UTC),
            end_time=datetime(2026, 9, 2, tzinfo=UTC),
            info={},
        )

        with (
            mock.patch("ranking.management.modules.nerc_itmo.REQ.get", side_effect=[html, "<root/>"]),
            mock.patch("ranking.management.modules.nerc_itmo.parse_xml", return_value={}),
        ):
            standings = parser.get_standings()

        row = standings["result"]["Alpha 2026-2027"]
        assert row["medal"] == "gold"
        assert row["_medal"] == "extra"
        assert "_{f}" not in row
