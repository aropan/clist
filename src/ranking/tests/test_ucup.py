from itertools import permutations
from unittest import mock

from django.test import SimpleTestCase

from ranking.management.modules.ucup import Statistic


class UcupSubmissionSelectionTest(SimpleTestCase):
    @staticmethod
    def submission(submission_id, verdict):
        return {
            "submission_id": submission_id,
            "verdict": verdict,
            "file_size": f"{submission_id}b",
            "url": f"https://example.com/submission/{submission_id}",
        }

    def merge_submissions(self, submissions):
        problem = {}
        for submission in submissions:
            Statistic._update_upsolving_submission(problem, submission)
        return problem

    def test_selection_does_not_depend_on_submission_order(self):
        submissions = [
            self.submission(10, "WA"),
            self.submission(12, "WA"),
            self.submission(11, "AC"),
            self.submission(13, "AC"),
        ]

        for ordered_submissions in permutations(submissions):
            with self.subTest(order=[submission["submission_id"] for submission in ordered_submissions]):
                problem = self.merge_submissions(ordered_submissions)
                assert problem["submission_id"] == 11
                assert problem["verdict"] == "AC"
                assert problem["file_size"] == "11b"
                assert problem["attempts"] == 2
                assert problem["result"] == "+2"

    def test_latest_submission_is_selected_without_accepted_submission(self):
        submissions = [self.submission(10, "WA"), self.submission(12, "TL")]

        for ordered_submissions in permutations(submissions):
            with self.subTest(order=[submission["submission_id"] for submission in ordered_submissions]):
                problem = self.merge_submissions(ordered_submissions)
                assert problem["submission_id"] == 12
                assert problem["verdict"] == "TL"
                assert problem["attempts"] == 2
                assert problem["result"] == "-2"

    def test_rejected_submission_does_not_replace_existing_accepted_result(self):
        problem = self.submission(10, "AC") | {"result": "+"}

        Statistic._update_upsolving_submission(problem, self.submission(12, "WA"))

        assert problem["submission_id"] == 10
        assert problem["verdict"] == "AC"
        assert problem["attempts"] == 1
        assert problem["result"] == "+1"

    def test_submission_pages_and_submissions_are_processed_once(self):
        page_data = {
            1: ([self.submission(10, "WA")], [1, 2, 3, 2]),
            2: ([self.submission(20, "WA")], [3, 4]),
            3: ([self.submission(20, "WA"), self.submission(30, "AC")], [4]),
            4: ([], []),
        }
        fetch_submission_page = mock.Mock(side_effect=lambda page: page_data[page])
        processed_submission_ids = []

        seen_pages, seen_submission_ids = Statistic._process_submission_pages(
            fetch_submission_page,
            lambda submission: processed_submission_ids.append(submission["submission_id"]),
        )

        assert seen_pages == {1, 2, 3, 4}
        assert seen_submission_ids == {10, 20, 30}
        assert processed_submission_ids == [10, 20, 30]
        assert sorted(call.args[0] for call in fetch_submission_page.call_args_list) == [1, 2, 3, 4]


class UcupRequestTest(SimpleTestCase):
    def test_rating_urls_include_current_and_archive_pages(self):
        assert Statistic._get_rating_urls("5") == (
            "https://ucup.ac/rating/",
            "https://ucup.ac/archive/season5/rating/",
        )

    @mock.patch("ranking.management.modules.ucup.REQ.get")
    def test_rating_page_uses_archive_when_current_page_has_another_season(self, request_get):
        request_get.side_effect = ["The 5th Universal Cup", "archived rating"]

        assert Statistic._get_rating_page("3") == "archived rating"
        assert request_get.call_args_list == [
            mock.call("https://ucup.ac/rating/"),
            mock.call("https://ucup.ac/archive/season3/rating/"),
        ]

    @mock.patch("ranking.management.modules.ucup.REQ.get")
    def test_rating_page_uses_current_page_for_detected_season(self, request_get):
        request_get.return_value = "The 5th Universal Cup current rating"

        assert Statistic._get_rating_page("5") == "The 5th Universal Cup current rating"
        request_get.assert_called_once_with("https://ucup.ac/rating/")

    @mock.patch("ranking.management.modules.ucup.REQ.get", return_value=("problem page", 200))
    def test_problem_page_retries_rate_limit_with_delay(self, request_get):
        url = "https://contest.ucup.ac/contest/3766/problem/17351"

        assert Statistic._get_problem_page(url) == ("problem page", 200)
        request_get.assert_called_once_with(
            url,
            return_code=True,
            ignore_codes={404},
            additional_attempts={429: {"count": 1}},
            additional_delay=60,
        )


class UcupSeasonRatingTest(SimpleTestCase):
    rating_page = """
        <table>
          <tr><th>#</th><th>Team name</th><th>Rating</th>
            <th><a href="https://contest.ucup.ac/contest/1">First</a></th>
            <th><a href="https://contest.ucup.ac/contest/2">Second</a></th></tr>
          <tr><td>1</td><td><a href="/user/profile/ucup-team00087">Renamed team (Member)</a></td>
            <td>200</td><td>A</td><td>200</td></tr>
          <tr><td>2</td><td><a href="/user/profile/ucup-team1878">Another team (Member)</a></td>
            <td>100</td><td>0</td><td>100</td></tr>
        </table>
    """

    def module(self, contest_id=1):
        return Statistic(
            key="ucup-4-stage-1",
            standings_url=f"https://contest.ucup.ac/contest/{contest_id}/standings/",
            info={"parse": {"season": "4", "stage": "stage-1"}, "standings": {"parse_submissions": False}},
        )

    def test_author_and_zero_scores_are_matched_by_profile_id(self):
        with mock.patch.object(Statistic, "_get_rating_page", return_value=self.rating_page):
            ratings = self.module()._get_season_ratings()

        assert ratings["team-87"] == {"season_rating": "A"}
        assert ratings["Renamed team"] == {"season_rating": "A"}
        assert ratings["team-1878"] == {"season_rating": 0}

    def test_rating_column_is_selected_by_contest_url(self):
        module = self.module(2)
        missing_module = self.module(3)
        with mock.patch.object(Statistic, "_get_rating_page", return_value=self.rating_page):
            ratings = module._get_season_ratings()
            missing = missing_module._get_season_ratings()

        assert ratings["team-87"] == {"season_rating": 200}
        assert module._season_rating_ranking == {"team-87": 1, "team-1878": 2}
        assert not missing
        assert missing_module._season_rating_ranking is None

    def test_participants_exclude_authors_zero_and_empty_scores(self):
        module = self.module()
        with mock.patch.object(Statistic, "_get_rating_page", return_value=self.rating_page):
            module._get_season_ratings()

        assert module._season_rating_ranking == {}
        assert module._season_rating_writers == ["team-87"]

    def test_unpublished_rating_table_does_not_mean_no_participants(self):
        module = self.module()
        with mock.patch.object(Statistic, "_get_rating_page", return_value="<h1>Ratings will be published later</h1>"):
            ratings = module._get_season_ratings()

        assert not ratings
        assert module._season_rating_ranking is None

    def test_ranking_includes_custom_handles_and_shared_places(self):
        extra_rows = """
          <tr><td>3</td><td><a href="/user/profile/MIT1">Monkey is Typing</a></td>
            <td>100</td><td>150</td><td></td></tr>
          <tr><td>4</td><td>123</td><td>100</td><td>150</td><td></td></tr>
          <tr><td>5</td><td><a href="/user/profile/custom-team">Another</a></td>
            <td>100</td><td>100</td><td></td></tr>
        """
        module = self.module()
        page = self.rating_page.replace("</table>", extra_rows + "</table>")
        with mock.patch.object(Statistic, "_get_rating_page", return_value=page):
            ratings = module._get_season_ratings()

        assert ratings["MIT1"] == {"season_rating": 150}
        assert module._season_rating_ranking == {"MIT1": 1, "123": 1, "custom-team": 3}

    def test_fifth_season_writer_marker_is_preserved(self):
        with mock.patch.object(Statistic, "_get_rating_page", return_value=self.rating_page.replace(">A<", ">W<")):
            ratings = self.module()._get_season_ratings()

        assert ratings["team-87"] == {"season_rating": "W"}

    def test_author_without_a_standings_row_is_returned_as_writer(self):
        standings_page = """
contest_type = "ICPC";
standings = [[100, 120, ["ucup-team1878", 1000, 0, "Old team name (Member)"], 1, 100]];
score = {"ucup-team1878": {"0": [100, 120, 1, 0, 100]}};
problems = [1];
problems_id = ["A"];
        """
        with (
            mock.patch.object(Statistic, "_get_rating_page", return_value=self.rating_page),
            mock.patch("ranking.management.modules.ucup.REQ.get", return_value=standings_page),
            mock.patch("ranking.management.modules.ucup.REQ.add_cookie"),
            mock.patch.object(Statistic, "_get_problem_page", return_value=("<h1>A. Task</h1>", 200)),
        ):
            standings = self.module().get_standings()

        assert standings["writers"] == ["team-87"]
        assert standings["_season_rating_ranking"] == {}
        assert "_season_rating_ranking" in standings["info_fields"]
        assert "team-87" not in standings["result"]
        assert standings["result"]["team-1878"]["season_rating"] == 0
