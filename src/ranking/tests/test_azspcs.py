from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from ranking.management.modules.azspcs import REQ, Statistic


class AzspcsHostTest(SimpleTestCase):
    def test_rejects_other_hosts_before_requesting_standings(self):
        for url in (
            "https://notazspcs.com/Contest/123",
            "https://azspcs.com.evil.example/Contest/123",
            "https://evil.example/azspcs.com/Contest/123",
            "https:///Contest/123",
        ):
            with self.subTest(url=url), patch.object(REQ, "get") as request_get:
                assert Statistic(url=url).get_standings() == {"action": "skip"}
                request_get.assert_not_called()

    def test_requests_standings_for_azspcs_subdomain(self):
        statistic = Statistic(url="https://www.azspcs.com/Contest/123")
        statistic.contest = SimpleNamespace(is_over=lambda: False)
        with patch.object(REQ, "get", return_value="") as request_get:
            statistic.get_standings()
        request_get.assert_called_once_with("https://www.azspcs.com/Contest/123/Standings")
