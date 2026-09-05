from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from ranking.management.modules.open_kattis import REQ, Statistic


class OpenKattisUsersInfoTest(SimpleTestCase):
    def test_parses_profile_strip(self):
        page = """
            <div class="image_info">
                <div class="image_info-image-container image_info-image-container-header">
                    <img src="/images/users/zii?v=avatar" alt="Oskar Haarklou Veileborg">
                </div>
                <div class="image_info-text-container">
                    <div class="image_info-text-horizontal">
                        <a href="/users/zii">
                            <span class="image_info-text-main">Oskar Haarklou Veileborg</span>
                        </a>
                    </div>
                </div>
            </div>
            <div class="divider_list-item divider_list-item-first">
                <span class="info_label">Rank</span>
                <span class="important_text">13</span>
            </div>
            <div class="divider_list-item">
                <span class="info_label">Score</span>
                <span class="important_text">9104.1</span>
            </div>
            <div class="image_info">
                <div class="image_info-image-container">
                    <a href="/countries/DNK" title="Denmark"></a>
                </div>
                <div><a href="/countries/DNK">Denmark</a></div>
            </div>
            <div class="image_info">
                <div class="image_info-image-container">
                    <a href="/countries/DNK/82" title="Central Jutland"></a>
                </div>
                <div><a href="/countries/DNK/82">Central Jutland</a></div>
            </div>
            <div class="image_info">
                <div class="image_info-image-container">
                    <a href="/affiliations/au.dk" title="Aarhus University"></a>
                </div>
                <div><a href="/affiliations/au.dk">Aarhus University</a></div>
            </div>
        """
        resource = SimpleNamespace(profile_url="https://open.kattis.com/users/{account}")

        with mock.patch.object(REQ, "get", return_value=page):
            infos = list(Statistic.get_users_infos(["zii"], resource=resource))

        assert infos == [
            {
                "info": {
                    "name": "Oskar Haarklou Veileborg",
                    "country": "DNK",
                    "subdivision": "Central Jutland",
                    "university": "Aarhus University",
                    "avatar_url": "https://open.kattis.com/images/users/zii?v=avatar",
                    "rating": 9104.1,
                    "rank": 13,
                }
            }
        ]
