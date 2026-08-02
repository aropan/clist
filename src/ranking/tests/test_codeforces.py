import os
from unittest import mock

from django.test import SimpleTestCase

from ranking.management.modules.codeforces import REQ, Statistic


class CodeforcesUsersInfoTest(SimpleTestCase):
    def test_retries_after_missing_handle_response_without_result(self):
        responses = [
            {
                "status": "FAILED",
                "comment": "handles: User with handle missing_handle not found",
            },
            {
                "status": "OK",
                "result": [{"handle": "tourist"}],
            },
        ]

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("ranking.management.modules.codeforces.api_query", side_effect=responses) as api_query,
            mock.patch.object(REQ, "get") as request_get,
            mock.patch.object(REQ, "geturl", return_value="https://codeforces.com/"),
        ):
            infos = list(Statistic.get_users_infos(["missing_handle", "tourist"]))

        assert infos == [
            {"delete": True},
            {
                "info": {"handle": "tourist", "name": ""},
                "special_info_fields": {"name_ru"},
            },
        ]
        assert api_query.call_count == 2
        request_get.assert_not_called()
