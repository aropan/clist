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
