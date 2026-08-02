import functools
import io
from unittest import mock

from django.test import SimpleTestCase

from logify.live import tqdm
from ranking.management.modules import algoleague


class ModuleProgressTest(SimpleTestCase):
    def test_dynamic_standings_pages_progress_completes(self):
        statistic = object.__new__(algoleague.Statistic)
        statistic.url = "https://example.com/contest"
        statistic.info = {"parse": {"id": "contest-id", "participationType": "individual"}}

        responses = [
            {"items": []},
            {"items": [], "totalCount": 150},
            {"items": [], "totalCount": 150},
        ]
        session = mock.Mock()
        session.next_bar_id.return_value = "standings-pages"
        live_tqdm = functools.partial(tqdm, file=io.StringIO(), mininterval=0)

        with (
            mock.patch("logify.live.get_current_session", return_value=session),
            mock.patch("ranking.management.modules.algoleague.tqdm", live_tqdm),
            mock.patch("ranking.management.modules.algoleague.REQ.get", side_effect=responses),
        ):
            statistic.get_standings()

        completed = [call.kwargs for call in session.progress.call_args_list if call.kwargs["completed"]]
        assert completed[-1]["description"] == "standings pages"
        assert completed[-1]["current"] == 2
        assert completed[-1]["total"] == 2

    def test_empty_standings_still_completes_the_fetched_page(self):
        statistic = object.__new__(algoleague.Statistic)
        statistic.url = "https://example.com/contest"
        statistic.info = {"parse": {"id": "contest-id", "participationType": "individual"}}

        session = mock.Mock()
        session.next_bar_id.return_value = "standings-pages"
        live_tqdm = functools.partial(tqdm, file=io.StringIO(), mininterval=0)

        with (
            mock.patch("logify.live.get_current_session", return_value=session),
            mock.patch("ranking.management.modules.algoleague.tqdm", live_tqdm),
            mock.patch(
                "ranking.management.modules.algoleague.REQ.get",
                side_effect=[{"items": []}, {"items": [], "totalCount": 0}],
            ),
        ):
            statistic.get_standings()

        completed = [call.kwargs for call in session.progress.call_args_list if call.kwargs["completed"]]
        assert completed[-1]["current"] == 1
        assert completed[-1]["total"] == 1
