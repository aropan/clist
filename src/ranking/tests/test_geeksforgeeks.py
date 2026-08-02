import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from ranking.management.modules import geeksforgeeks


class GeeksForGeeksProfileTest(SimpleTestCase):
    def test_get_users_infos_parses_app_router_profile(self):
        profile = [
            "$",
            "$L31",
            None,
            {
                "mentor": {"handle": "tourist"},
                "username": "tourist",
                "articleCount": {
                    "name": "Tourist",
                    "profile_image_url": "https://example.com/avatar.png",
                    "organization_name": "Example",
                    "score": 42,
                    "total_problems_solved": 100,
                },
            },
        ]
        flight_data = f"6:{json.dumps(profile)}\n"
        split = len(flight_data) // 2
        page = "".join(
            f"<script>self.__next_f.push({json.dumps([1, chunk])})</script>"
            for chunk in (flight_data[:split], flight_data[split:])
        )
        account = SimpleNamespace(
            key="tourist",
            profile_url=lambda resource: "https://www.geeksforgeeks.org/user/tourist/",
        )

        with patch.object(geeksforgeeks.REQ, "get", return_value=page):
            result = list(geeksforgeeks.Statistic.get_users_infos(["tourist"], object(), [account]))

        assert result == [
            {
                "info": {
                    "name": "Tourist",
                    "profile_image_url": "https://example.com/avatar.png",
                    "organization_name": "Example",
                    "score": 42,
                    "total_problems_solved": 100,
                },
            }
        ]

    def test_get_users_infos_skips_unknown_profile_format(self):
        account = SimpleNamespace(
            key="tourist",
            profile_url=lambda resource: "https://www.geeksforgeeks.org/user/tourist/",
        )

        with patch.object(geeksforgeeks.REQ, "get", return_value="<html></html>"):
            result = list(geeksforgeeks.Statistic.get_users_infos(["tourist"], object(), [account]))

        assert result == [{"skip": True}]
