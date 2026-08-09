from django.test import SimpleTestCase

from ranking.management.modules.excepts import ExceptionParseStandings
from ranking.management.modules.leetcode import Statistic


class LeetcodeStoredRankingPagesTest(SimpleTestCase):
    def test_extracts_pages_for_known_ranking_urls(self):
        users = ["alice@leetcode.com", "bob@leetcode.cn", "upsolver@leetcode.com"]
        statistics = {
            "alice@leetcode.com": {
                "url": "https://leetcode.com/contest/weekly-contest-512/ranking/708/",
            },
            "bob@leetcode.cn": {
                "url": "https://leetcode.cn/contest/weekly-contest-512/ranking/47/",
            },
            "upsolver@leetcode.com": {"problems": {"Q1": {"upsolving": {"result": "+"}}}},
        }

        users_with_pages, pages = Statistic._stored_ranking_pages(users, statistics)

        assert users_with_pages == ["alice@leetcode.com", "bob@leetcode.cn"]
        assert dict(pages) == {".com": {707}, ".cn": {46}}

    def test_rejects_non_ranking_and_external_urls(self):
        assert Statistic._ranking_page_from_url("https://leetcode.com/u/alice/") is None
        assert Statistic._ranking_page_from_url("https://example.com/ranking/10/") is None
        assert Statistic._ranking_page_from_url("https://leetcode.com/contest/test/ranking/0/") is None

    def test_requires_stored_pages_for_every_ranked_user(self):
        users = ["ranked@leetcode.com", "upsolver@leetcode.com", "skipped@leetcode.cn"]
        statistics = {
            "ranked@leetcode.com": {"url": "https://leetcode.com/contest/test/ranking/10/"},
            "upsolver@leetcode.com": {"_no_update_n_contests": True},
            "skipped@leetcode.cn": {"_skip_on_update": True},
        }
        users_with_pages, _ = Statistic._stored_ranking_pages(users, statistics)

        assert Statistic._has_stored_ranking_page_coverage(users, users_with_pages, statistics)

        statistics["upsolver@leetcode.com"].pop("_no_update_n_contests")
        assert not Statistic._has_stored_ranking_page_coverage(users, users_with_pages, statistics)

    def test_adds_neighbor_pages_and_clamps_to_standings(self):
        pages = Statistic._ranking_pages_with_neighbors({0, 99}, total_pages=100)

        assert pages == [0, 1, 2, 99, 98, 97]

    def test_invalid_saved_place_fails_instead_of_fetching_all_pages(self):
        with self.assertRaisesMessage(ExceptionParseStandings, "Invalid place unknown"):
            Statistic._ranking_pages_from_statistics(
                ["alice@leetcode.com"],
                {"alice@leetcode.com": {"place": "unknown"}},
                per_page=25,
            )
