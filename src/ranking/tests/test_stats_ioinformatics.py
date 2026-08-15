from django.test import SimpleTestCase

from ranking.management.modules.stats_ioinformatics import get_official_ranking_base_url


class OfficialRankingUrlTest(SimpleTestCase):
    def test_explicit_ranking_url_takes_precedence(self):
        info = {
            "_official_website_ranking": "https://ranking.ioi2025.bo",
            "parse": {"website": "https://ioi2025.obi.org.bo"},
        }

        assert get_official_ranking_base_url(info) == "https://ranking.ioi2025.bo"

    def test_ranking_url_is_derived_when_override_is_missing(self):
        info = {"parse": {"website": "https://ioi2024.eg/path//kept"}}

        assert get_official_ranking_base_url(info) == "https://ranking.ioi2024.eg/path//kept"

    def test_missing_website_disables_ranking_enrichment(self):
        assert get_official_ranking_base_url({}) is None
