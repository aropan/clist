import functools
import io
from unittest import mock

from django.test import SimpleTestCase

from logify.live import tqdm
from ranking.management.modules import atcoder


class AtCoderSubmissionsProgressTest(SimpleTestCase):
    def test_early_stop_completes_single_cumulative_pages_progress(self):
        statistic = object.__new__(atcoder.Statistic)
        statistic._stop = None
        statistic._forbidden = None

        class NonEmptyTable:
            def __iter__(self):
                return iter(())

        def fetch_submissions(fuser=None, c_page=1):
            if c_page == 5:
                return None
            return "url", "page", NonEmptyTable(), c_page

        statistic.fetch_submissions = mock.Mock(side_effect=fetch_submissions)
        standings = {
            "result": {},
            "_submissions_info": {
                "last_page": 1,
            },
        }

        session = mock.Mock()
        session.next_bar_id.side_effect = ["first-pages", "submission-pages"]
        progress_output = io.StringIO()
        live_tqdm = functools.partial(tqdm, file=progress_output, mininterval=0)

        with (
            mock.patch("logify.live.get_current_session", return_value=session),
            mock.patch("ranking.management.modules.atcoder.tqdm", live_tqdm),
        ):
            statistic._update_submissions([None], standings)

        events = [call.kwargs for call in session.progress.call_args_list]
        assert {event["bar_id"] for event in events} == {"first-pages", "submission-pages"}

        submissions_events = [event for event in events if event["bar_id"] == "submission-pages"]
        assert submissions_events[-1]["description"] == "getting submissions: pages (1;7]", submissions_events
        assert submissions_events[-1]["current"] == 6
        assert submissions_events[-1]["total"] == 6
        assert submissions_events[-1]["completed"] is True
        assert sum(event["completed"] for event in submissions_events) == 1
        assert statistic._stop is True
