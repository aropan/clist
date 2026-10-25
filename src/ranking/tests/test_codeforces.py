import os
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils.timezone import now

from clist.models import Contest, Resource
from ranking.management.modules import codeforces
from ranking.management.modules.codeforces import REQ, Statistic
from ranking.models import Account, Statistics


class CodeforcesAccountSubmissionsTest(TestCase):
    def test_interleaved_contests_keep_account_totals(self):
        with mock.patch.object(Resource, "update_icon"):
            resource = Resource.objects.create(host="codeforces.com", url="https://codeforces.com/", enable=True)
        account = Account.objects.create(resource=resource, key="coder")
        for contest_id in (16, 17):
            Contest.objects.create(
                resource=resource,
                key=str(contest_id),
                title=f"Round {contest_id}",
                url=f"https://codeforces.com/contest/{contest_id}",
                start_time=now() - timedelta(days=2),
                end_time=now() - timedelta(days=1),
            )
        submissions = [
            {
                "id": submission_id,
                "contestId": contest_id,
                "verdict": verdict,
                "author": {"participantType": "PRACTICE", "members": [{"handle": account.key}]},
                "problem": {"index": "A"},
            }
            for submission_id, contest_id, verdict in (
                (153, 16, "WRONG_ANSWER"),
                (152, 17, "OK"),
                (151, 16, "OK"),
            )
        ]

        with mock.patch.object(codeforces, "api_query", return_value={"result": submissions}):
            Statistic.update_submissions(account, resource, with_submissions=False, pagination_size=None)

        statistics = Statistics.objects.filter(account=account)
        assert statistics.count() == 2
        assert all(stat.addition["problems"]["A"]["upsolving"]["result"] == "+" for stat in statistics)
        account.refresh_from_db()
        assert account.n_upsolved == 2
        assert account.total_solving == 2


class CodeforcesApiQueryTest(SimpleTestCase):
    def test_default_rate_limit_history_is_shared_between_calls(self):
        api_key = ("test", "secret")
        with (
            mock.patch.dict(codeforces._API_QUERY_TIMES, {}, clear=True),
            mock.patch.object(REQ, "get", return_value={"status": "OK"}),
        ):
            codeforces.api_query("user.info", {"handles": "alice"}, api_key=api_key)
            codeforces.api_query("user.info", {"handles": "bob"}, api_key=api_key)
            assert len(codeforces._API_QUERY_TIMES[api_key]) == 2

            custom_history = {}
            codeforces.api_query("user.info", {"handles": "carol"}, api_key=api_key, prev_time_queries=custom_history)
            assert len(custom_history[api_key]) == 1
            assert len(codeforces._API_QUERY_TIMES[api_key]) == 2


class CodeforcesStandingsTest(SimpleTestCase):
    def test_selected_user_ratings_are_assigned_to_matching_handles(self):
        current_time = now()
        contest = SimpleNamespace(
            pk=1,
            title="Codeforces test",
            url="https://codeforces.com/contests/1234",
            key="1234",
            standings_url=None,
            start_time=current_time - timedelta(days=2),
            end_time=current_time - timedelta(days=1),
            info={},
            resource=SimpleNamespace(),
            invisible=False,
            elimination_tournament_info=None,
        )
        rows = [
            {
                "party": {"participantType": "CONTESTANT", "members": [{"handle": handle}]},
                "rank": rank,
                "points": 0,
                "successfulHackCount": 0,
                "unsuccessfulHackCount": 0,
                "problemResults": [],
            }
            for rank, handle in enumerate(("alice", "bob", "unselected"), start=1)
        ]

        def api_query(method, **kwargs):
            if method == "contest.standings":
                return {
                    "status": "OK",
                    "result": {
                        "contest": {"phase": "FINISHED", "type": "CF", "durationSeconds": 7200},
                        "problems": [],
                        "rows": rows,
                    },
                }
            if method == "contest.status":
                return {"status": "OK", "result": []}
            raise AssertionError(f"unexpected API method: {method}")

        statistics = {
            "alice": {"old_rating": 100, "new_rating": 150},
            "bob": {"old_rating": 200, "new_rating": 250},
        }
        with mock.patch("ranking.management.modules.codeforces.api_query", side_effect=api_query):
            standings = Statistic(contest=contest).get_standings(
                users=["alice", "bob"],
                statistics=statistics,
            )

        assert standings["result"]["alice"]["old_rating"] == 100
        assert standings["result"]["alice"]["new_rating"] == 150
        assert standings["result"]["bob"]["old_rating"] == 200
        assert standings["result"]["bob"]["new_rating"] == 250
        assert "old_rating" not in standings["result"]["unselected"]


class CodeforcesUsersInfoTest(SimpleTestCase):
    def test_normalizes_photo_urls_before_building_avatar_url(self):
        resource = Resource(
            host="codeforces.com",
            avatar_url="https://codeforces.com/{info[avatar]}",
        )
        avatar = "userpic.codeforces.org/1706822/avatar/b7d7c24d111ea1df.jpg"
        title_photo = "userpic.codeforces.org/1706822/title/b7d7c24d111ea1df.jpg"
        for prefix in (
            "https://",
            "http://",
            "//",
            "",
            "/",
            "https://codeforces.com/",
            "//codeforces.com/",
            "codeforces.com/",
        ):
            with (
                self.subTest(prefix=prefix),
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch.object(
                    codeforces,
                    "api_query",
                    return_value={
                        "status": "OK",
                        "result": [{"handle": "coder", "avatar": prefix + avatar, "titlePhoto": prefix + title_photo}],
                    },
                ),
            ):
                (result,) = Statistic.get_users_infos(["coder"], resource)

            assert result["info"]["avatar"] == avatar
            assert result["info"]["titlePhoto"] == title_photo
            account = Account(resource=resource, key="coder", info=result["info"])
            assert account.avatar_url() == f"https://codeforces.com/{avatar}"

    def test_preserves_other_photo_hosts_and_paths(self):
        photos = {
            "avatar": "https://codeforces.com/images/custom-avatar.jpg",
            "titlePhoto": "https://sta.codeforces.com/images/custom-title.jpg",
        }
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                codeforces,
                "api_query",
                return_value={"status": "OK", "result": [{"handle": "coder", **photos}]},
            ),
        ):
            (result,) = Statistic.get_users_infos(["coder"])

        for field, photo in photos.items():
            assert result["info"][field] == photo

    def test_removes_default_and_empty_photos(self):
        resource = Resource(host="codeforces.com", avatar_url="https://codeforces.com/{info[avatar]}")
        for prefix in ("https://", "//", ""):
            photos = {
                "avatar": f"{prefix}userpic.codeforces.org/no-avatar.jpg",
                "titlePhoto": f"{prefix}userpic.codeforces.org/no-title.jpg",
            }
            self.assert_photos_removed(resource, photos)
        for value in ("", None):
            self.assert_photos_removed(resource, {"avatar": value, "titlePhoto": value})

    def assert_photos_removed(self, resource, photos):
        with (
            self.subTest(photos=photos),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                codeforces,
                "api_query",
                return_value={"status": "OK", "result": [{"handle": "coder", **photos}]},
            ),
        ):
            (result,) = Statistic.get_users_infos(["coder"], resource)

        assert "avatar" not in result["info"]
        assert "titlePhoto" not in result["info"]
        assert Account(resource=resource, key="coder", info=result["info"]).avatar_url() is None

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
                "canonical_key": "tourist",
                "special_info_fields": {"name_ru"},
            },
        ]
        assert api_query.call_count == 2
        request_get.assert_not_called()
