from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta
from threading import Event
from types import SimpleNamespace
from unittest import mock

import pytest
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from clist.models import Contest, Resource
from clist.templatetags.extras import is_solved
from clist.utils import update_writers
from ranking.management.commands.parse_statistic import Command
from ranking.management.modules import codearena
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse
from ranking.models import Account, AccountRenaming, Module, Statistics
from ranking.utils import account_update_contest_additions


def contest(**changes):
    return {
        "id": 20,
        "kind": "round",
        "rules": "cf",
        "status": "past",
        "is_rated": True,
        "rating_applied": True,
        "authors": ["c0de"],
        "standings_url": "https://codearena.uz/contests/20/standings/",
        "start_time": "2026-10-22T08:25:00Z",
        "end_time": "2026-10-22T09:35:00Z",
        "duration_minutes": 70,
        "personal_minutes": None,
        **changes,
    }


def problem(short="A"):
    return {
        "label": short,
        "title": "Sign-up",
        "slug": f"task-{short}",
        "url": "https://codearena.uz/problems/task/",
        "points": 250,
        "difficulty": "beginner",
        "rating": 400,
    }


def cell(**changes):
    return {
        "result": "+",
        "points": 242,
        "wrong_tries": 0,
        "minutes": 5,
        "time": "00:05",
        "first_solve": True,
        **changes,
    }


def entry(member="ruxwon", **changes):
    return {
        "member": member,
        "name": "Participant",
        "country": "UZ",
        "place": 1,
        "score": 242,
        "solved": 1,
        "penalty": 0,
        "author": False,
        "disqualified": False,
        "out_of_competition": False,
        "rating_before": 0,
        "rating_after": 445,
        "rating_change": 445,
        "problems": {"A": cell()},
        **changes,
    }


def page(rows, number=1, size=200, count=None, **changes):
    count = len(rows) if count is None else count
    return {
        "status": "ok",
        "page": number,
        "pagesCount": (count + size - 1) // size,
        "pageSize": size,
        "count": count,
        "data": rows,
        "contest": contest(),
        "hidden": False,
        "problems": [problem()],
        **changes,
    }


class CodeArenaTests(SimpleTestCase):
    def setUp(self):
        self.parser = codearena.Statistic(key="20")
        self.get = self.enterContext(mock.patch.object(codearena.REQ, "get"))
        self.enterContext(mock.patch.object(codearena, "request_limiter", nullcontext()))

    def parse(self, *rows, **metadata):
        self.get.side_effect = None
        self.get.return_value = page(list(rows), **metadata)
        return self.parser.get_standings()

    def test_complete_pagination_and_selection_preserve_official_ranks(self):
        first = page([entry()], size=1, count=2)
        second = page([entry("Islomjon11", place=1)], number=2, size=1, count=2)
        self.get.side_effect = [first, second]
        previous = {"unrelated": {"problems": {"A": {"result": 999}}}}
        saved = deepcopy(previous)
        result = self.parser.get_standings(users=["Islomjon11"], statistics=previous)
        assert result["result"]["Islomjon11"]["place"] == 1
        assert list(result["result"]) == ["Islomjon11"]
        assert previous == saved
        assert [call.args[0] for call in self.get.call_args_list] == [
            f"https://codearena.uz/api/v1/contests/20/standings/?page={p}&page_size=200" for p in (1, 2)
        ]
        assert all(
            call.kwargs["raise_codes"] == {404, 429} and call.kwargs["n_attempts"] == 1
            for call in self.get.call_args_list
        )

    def test_failed_api_responses_raise(self):
        for response in (None, [], {}, page([]) | {"status": "error"}):
            with self.subTest(response=response):
                self.get.return_value = response
                with pytest.raises(ExceptionParseStandings):
                    self.parser.get_standings()

    def test_later_page_failure_does_not_return_partial_results(self):
        for failure in (http_error(429), ValueError("bad JSON"), {"status": "error"}):
            with self.subTest(failure=failure):
                self.get.side_effect = [page([entry()], size=1, count=2), failure]
                with pytest.raises(ExceptionParseStandings):
                    self.parser.get_standings(users=[])

    def test_pagination_only_needs_page_count_and_rows(self):
        first = page([entry()], size=1, count=2)
        for field in ("page", "pageSize", "count"):
            first.pop(field)
        self.get.side_effect = [
            first,
            {"status": "ok", "pagesCount": 2, "data": [entry("second", place=2)], "new_metadata": {}},
        ]
        result = self.parser.get_standings()["result"]
        assert list(result) == ["ruxwon", "second"]
        assert result["second"]["place"] == 2

    def test_unknown_rules_are_reported(self):
        self.get.return_value = page([], contest=contest(rules="unknown"))
        with pytest.raises(ExceptionParseStandings, match="Unknown rules 'unknown' for contest 20"):
            self.parser.get_standings()

    def test_optional_standings_fields_can_be_omitted(self):
        item = entry()
        for field in (
            "name",
            "country",
            "penalty",
            "solved",
            "author",
            "disqualified",
            "out_of_competition",
            *codearena.RATING_FIELDS,
        ):
            item.pop(field)
        item["problems"] = {"A": {"result": "+", "points": 242, "new_metadata": {"value": 1}}}
        result = self.parse(
            item,
            contest=contest(id="20", new_metadata={"value": 2}),
            problems=[{"label": "A", "title": "Task", "new_metadata": {"value": 3}}],
        )
        row = result["result"]["ruxwon"]
        assert row["solving"] == row["problems"]["A"]["result"] == 242
        assert is_solved(row["problems"]["A"])
        assert "name" not in row
        assert "old_rating" not in row
        assert row["problems"]["A"]["new_metadata"] == {"value": 1}
        assert result["problems"] == [{"short": "A", "name": "Task", "new_metadata": {"value": 3}}]

    def test_cf_accepted_decayed_zero_scores_and_problem_metadata(self):
        standings = self.parse(
            entry(), entry("zero", score=0, problems={"A": cell(points=0, minutes=0, time="00:00", wrong_tries=2)})
        )
        row, zero = standings["result"].values()
        assert row["solving"] == 242
        assert row["penalty"] == 0
        assert row["old_rating"] == 0
        assert row["new_rating"] == row["rating_change"] == 445
        assert row["solved"] == {"solving": 1}
        accepted = row["problems"]["A"]
        assert accepted["result"] == 242
        assert is_solved(accepted)
        assert "partial" not in accepted
        assert accepted["first_ac"]
        assert accepted["time_in_seconds"] == 300
        assert zero["solving"] == 0
        assert zero["problems"]["A"]["result"] == 0
        assert is_solved(zero["problems"]["A"])
        assert zero["problems"]["A"]["penalty_score"] == 2
        assert zero["problems"]["A"]["time_in_seconds"] == 0
        assert standings["problems"] == [
            {
                "short": "A",
                "name": "Sign-up",
                "code": "task-A",
                "url": problem()["url"],
                "full_score": 250,
                "difficulty": "beginner",
                "rating": 400,
            }
        ]

    def test_icpc_and_score_semantics(self):
        problems = [problem(s) for s in "ABC"]
        cells = {"A": cell(), "B": cell(result="+2", wrong_tries=2), "C": cell(result="-3", points=0, wrong_tries=3)}
        result = self.parse(
            entry(score=999, solved=2, penalty=187, problems=cells), contest=contest(rules="icpc"), problems=problems
        )
        row = result["result"]["ruxwon"]
        assert row["solving"] == 2
        assert row["penalty"] == 187
        assert [p["result"] for p in row["problems"].values()] == ["+", "+2", "-3"]
        result = self.parse(entry(problems={"A": cell(result="-1", points=30)}), contest=contest(rules="score"))
        partial = result["result"]["ruxwon"]["problems"]["A"]
        assert partial["result"] == 30
        assert partial["partial"]
        assert not is_solved(partial)
        assert result["standings_kind"] == "scoring"

    def test_failures_untouched_problems_and_personal_marathon_time(self):
        result = self.parse(
            entry(problems={"A": cell(result="-3", points=0, wrong_tries=3)}), problems=[problem(), problem("B")]
        )
        cells = result["result"]["ruxwon"]["problems"]
        assert cells["A"]["result"] == "-3"
        assert "B" not in cells
        assert "last_activity" not in result["result"]["ruxwon"]
        result = self.parse(
            entry(
                problems={
                    "A": cell(minutes=7, time="00:07", solved_at="2026-10-19T10:33:38.272048Z"),
                    "B": cell(minutes=3, time="00:03", solved_at="2026-10-19T10:29:17.441000Z"),
                }
            ),
            contest=contest(
                kind="marathon",
                start_time="2026-10-19T03:00:00Z",
                end_time="2026-10-21T15:00:00Z",
                duration_minutes=3600,
                personal_minutes=120,
            ),
        )
        assert result["duration_in_secs"] == 7200
        assert result["result"]["ruxwon"]["problems"]["A"]["time_in_seconds"] == 420
        assert result["result"]["ruxwon"]["last_activity"] == datetime.fromisoformat("2026-10-19T10:33:38.272048Z")

    def test_eligibility_and_writers(self):
        result = self.parse(
            entry("c0de", author=True, place=None),
            entry("winner"),
            entry("dq", disqualified=True, place=2),
            entry("unrated", out_of_competition=True, place=3),
            entry("null", place=None, score=0, solved=0, problems={}),
        )
        rows = result["result"]
        for member in ("c0de", "dq"):
            assert rows[member]["place"] is None
            assert rows[member]["_no_update_n_contests"]
            assert rows[member]["is_rated"] is False
            assert "new_rating" not in rows[member]
        assert rows["winner"]["place"] == 1
        assert rows["unrated"]["place"] == 3
        assert rows["unrated"]["is_rated"] is False
        assert "_no_update_n_contests" not in rows["null"]
        assert result["writers"] == ["c0de"]
        assert result["writers_case_sensitive"]
        assert "is_rated" in result["hidden_fields"]
        assert self.parse(contest=contest(authors=[]))["writers"] == []

    def test_empty_rows_are_removed_but_attempts_and_zero_rating_changes_remain(self):
        empty = entry(score=0, solved=0, problems={}, rating_after=None, rating_change=None)
        standings = self.parse(
            empty | {"member": "empty"},
            empty | {"member": "author", "author": True},
            empty | {"member": "attempt", "place": 3, "problems": {"A": cell(result="-1", points=0, wrong_tries=1)}},
            empty | {"member": "rated", "place": 4, "rating_after": 800, "rating_change": 0},
            empty | {"member": "zero_rating", "place": 5, "rating_after": 0},
        )
        rows = standings["result"]
        assert list(rows) == ["attempt", "rated", "zero_rating"]
        assert rows["attempt"]["place"] == 3
        assert rows["attempt"]["problems"]["A"]["result"] == "-1"
        assert rows["rated"]["rating_change"] == 0
        assert rows["zero_rating"]["new_rating"] == 0

    def test_hidden_upcoming_visible_empty_and_pending_rating(self):
        end = timezone.now() + timedelta(days=2)
        for changes in ({"hidden": True}, {"contest": contest(status="upcoming")}):
            result = self.parse(**changes)
            assert result["action"] == "skip"
            assert result["keep_results"]
            assert "problems" not in result
            assert "result" not in result
            assert result["force_timing_statistic_delta"]
        hidden = self.parse(hidden=True, contest=contest(kind="marathon", status="running", end_time=end.isoformat()))
        assert hidden["timing_statistic_delta"] > timedelta(days=1)
        visible = self.parse()
        assert visible["result"] == {}
        assert visible["has_hidden_results"] is False
        pending = self.parse(entry(), contest=contest(rating_applied=False))
        assert "new_rating" not in pending["result"]["ruxwon"]
        assert pending["timing_statistic_delta"] == timedelta(hours=1)


def profile(username="Islomjon11", **changes):
    return {
        "status": "ok",
        "user": {
            "username": username,
            "rating": 1512,
            "max_rating": 1512,
            "name": "Participant",
            "country": "UZ",
            "duel_rating": 1310,
            "practice_points": 3565,
            "club": None,
            "on_board": True,
            **changes,
        },
    }


def history_entry(key=20, **changes):
    return {
        "contest_id": key,
        "contest": "A renamed title",
        "rating_before": 0,
        "rating_after": 445,
        "rating_change": 445,
        "place": 1,
        **changes,
    }


def http_error(code):
    return FailOnGetResponse(SimpleNamespace(code=code))


class CodeArenaAccountTests(SimpleTestCase):
    def setUp(self):
        self.get = self.enterContext(mock.patch.object(codearena.REQ, "get"))
        self.enterContext(mock.patch.object(codearena, "request_limiter", nullcontext()))

    def refresh(self, username="Islomjon11"):
        (result,) = codearena.Statistic.get_users_infos([username], None, [], pbar=None)
        return result

    def test_profiles_overlap_with_two_second_pacing_and_keep_input_order(self):
        second_done = Event()
        clock = [0]

        def request(url, **kwargs):
            member = url.split("/users/", 1)[1].split("/", 1)[0]
            if "/ratings/" in url:
                if member == "second":
                    second_done.set()
                return page([history_entry(20 if member == "first" else 16)])
            if member == "first":
                assert second_done.wait(timeout=5), "Other profiles must run while this request waits"
            return profile(member)

        def advance(seconds):
            clock[0] += seconds

        self.get.side_effect = request
        pbar = mock.Mock()
        with (
            mock.patch("utils.ratelimiter.time.monotonic", side_effect=lambda: clock[0]),
            mock.patch("utils.ratelimiter.time.sleep", side_effect=advance) as sleep,
        ):
            results = list(codearena.Statistic.get_users_infos(["first", "second"], None, [], pbar=pbar))

        sleep.assert_called_once_with(2)
        assert [result["canonical_key"] for result in results] == ["first", "second"]
        assert [list(result["contest_addition_update_params"]["update"]) for result in results] == [["20"], ["16"]]
        assert pbar.update.call_count == 2

    def test_threaded_failures_keep_results_aligned_with_accounts(self):
        def request(url, **kwargs):
            member = url.split("/users/", 1)[1].split("/", 1)[0]
            if member == "missing":
                raise http_error(404)
            if "/ratings/" in url:
                if member == "broken":
                    raise http_error(503)
                return page([])
            return profile(member)

        self.get.side_effect = request
        with mock.patch.object(codearena, "RateLimiter", return_value=nullcontext()):
            results = list(codearena.Statistic.get_users_infos(["missing", "valid", "broken"], None, []))

        assert results[0] == {"delete": True}
        assert results[1]["canonical_key"] == "valid"
        assert results[2] == {"skip": True, "delta": timedelta(hours=1)}

    def test_exact_encoded_identity_and_separate_profile_metrics(self):
        self.get.side_effect = [profile(), page([history_entry()])]
        result = self.refresh()
        assert result["canonical_key"] == "Islomjon11"
        assert "rename" not in result
        assert self.get.call_args_list[0].args[0] == "https://codearena.uz/api/v1/users/Islomjon11/"
        info = result["info"]
        assert info["rating"] == 1512
        assert info["duel_rating"] == 1310
        assert info["practice_points"] == 3565
        assert info["club"] is None
        self.get.side_effect = [profile("a/b +"), page([])]
        self.refresh("a/b +")
        assert self.get.call_args_list[-2].args[0] == "https://codearena.uz/api/v1/users/a%2Fb%20%2B/"

    def test_explicit_canonical_response_and_zero_rated_author(self):
        self.get.side_effect = [profile("Canonical"), page([])]
        result = self.refresh("requested")
        assert result["canonical_key"] == result["rename"] == "Canonical"
        assert "/users/Canonical/ratings/" in self.get.call_args_list[-1].args[0]
        self.get.side_effect = [
            profile("c0de", rating=0, max_rating=None, on_board=False, n_rated_contests=0),
            page([]),
        ]
        result = self.refresh("c0de")
        assert result["info"]["rating"] == 0
        assert result["info"]["max_rating"] is None
        assert result["contest_addition_update_params"] == {"update": {}, "by": "key"}

    def test_complete_paginated_history_uses_stable_ids_and_zero_values(self):
        self.get.side_effect = [
            profile(),
            page([history_entry()], size=1, count=2),
            page([history_entry(16, rating_before=445, rating_after=445, rating_change=0)], number=2, size=1, count=2),
        ]
        result = self.refresh()
        assert result["contest_addition_update_params"] == {
            "by": "key",
            "update": {
                "20": {"old_rating": 0, "new_rating": 445, "rating_change": 445},
                "16": {"old_rating": 445, "new_rating": 445, "rating_change": 0},
            },
        }
        assert self.get.call_count == 3
        assert all("/users/Islomjon11/" in call.args[0] for call in self.get.call_args_list)

    def test_profile_http_404_marks_deleted_and_other_failures_defer(self):
        self.get.side_effect = [http_error(404)]
        assert self.refresh() == {"delete": True}
        assert self.get.call_count == 1
        for code in (429, 503):
            self.get.side_effect = [http_error(code)]
            assert self.refresh() == {"skip": True, "delta": timedelta(hours=1)}

    def test_history_failures_never_publish_profile_or_delete_account(self):
        for failure in (
            http_error(404),
            http_error(429),
            http_error(503),
            ValueError("not JSON"),
            {"status": "error"},
        ):
            with self.subTest(failure=failure):
                self.get.side_effect = [profile(), page([history_entry()], size=1, count=2), failure]
                assert self.refresh() == {"skip": True, "delta": timedelta(hours=1)}

    def test_failed_profiles_defer_with_progress(self):
        for response in (None, {}, {"status": "error"}, {"status": "ok"}):
            self.get.side_effect = None
            self.get.return_value = response
            pbar = mock.Mock()
            assert list(codearena.Statistic.get_users_infos(["Islomjon11"], None, [], pbar=pbar)) == [
                {"skip": True, "delta": timedelta(hours=1)}
            ]
            pbar.update.assert_called_once_with()

    def test_profile_fields_are_preserved_without_a_fixed_schema(self):
        response = profile(club={"name": "Club"}, new_metric={"value": 7}, max_rating="1512")
        self.get.side_effect = [response, page([])]
        assert self.refresh()["info"] == {**response["user"], "full_name": response["user"]["name"]}
        self.get.side_effect = [{"status": "ok", "user": {"new_metric": 7}}, page([])]
        result = self.refresh()
        assert result["info"] == {"new_metric": 7}
        assert result["canonical_key"] == "Islomjon11"
        assert "rename" not in result

    def test_account_verification_reads_full_name_from_api(self):
        resource = SimpleNamespace(plugin=SimpleNamespace(Statistic=codearena.Statistic))
        account = SimpleNamespace(resource=resource, key="Islomjon11")
        for name in ("CLIST-verification Participant", "Participant CLIST-verification"):
            with self.subTest(name=name):
                self.get.side_effect = [profile(name=name), page([])]
                fields = codearena.Statistic.get_account_fields(account)
                assert "CLIST-verification" in fields["full_name"]
                assert "first_name" not in fields
                assert "last_name" not in fields

    def test_history_updates_only_supplied_rating_fields(self):
        self.get.side_effect = [
            profile(),
            page([{"contest_id": "20", "rating_after": 445, "new_metadata": {"value": 7}}]),
        ]
        assert self.refresh()["contest_addition_update_params"] == {
            "by": "key",
            "update": {"20": {"new_rating": 445}},
        }


class CodeArenaIngestionTests(TestCase):
    def setUp(self):
        self.resource = Resource(host="codearena-test.example", url="https://codearena.uz/", enable=False)
        Resource.objects.bulk_create([self.resource])
        Module.objects.create(
            resource=self.resource,
            path="ranking/management/modules/codearena",
            max_delay_after_end=timedelta(days=30),
            delay_on_error=timedelta(hours=1),
            delay_on_success=timedelta(hours=8),
        )
        self.contest = Contest(
            resource=self.resource,
            host=self.resource.host,
            key="20",
            title="CodeArena",
            url=contest()["standings_url"],
            start_time=timezone.now() - timedelta(days=4),
            end_time=timezone.now() - timedelta(days=1),
            duration_in_secs=7200,
        )
        Contest.objects.bulk_create([self.contest])
        self.get = self.enterContext(mock.patch.object(codearena.REQ, "get"))
        self.enterContext(mock.patch.object(codearena, "request_limiter", nullcontext()))
        self.enterContext(
            mock.patch.object(
                Resource,
                "plugin",
                new_callable=mock.PropertyMock,
                return_value=SimpleNamespace(Statistic=codearena.Statistic),
            )
        )

    def ingest(self, response):
        self.get.return_value = response
        Command().parse_statistic(
            Contest.objects.filter(pk=self.contest.pk),
            with_check=False,
            without_subscriptions=True,
            without_calculate_rating_prediction=True,
        )
        self.contest.refresh_from_db()

    def test_hidden_response_retains_saved_statistics_and_problems_until_publication(self):
        # The PHP schedule importer already supplied writers, but no M2M relations.
        self.contest.info["writers"] = ["c0de"]
        self.contest.save(update_fields=["info"])
        self.ingest(page([entry(), entry("c0de", author=True, place=None)]))
        stat = Statistics.objects.get(contest=self.contest, account__key="ruxwon")
        before = deepcopy(stat.addition)
        saved_problems = deepcopy(self.contest.info["problems"])
        assert list(self.contest.writers.values_list("key", flat=True)) == ["c0de"]
        author = Statistics.objects.get(contest=self.contest, account__key="c0de")
        assert author.skip_in_stats
        assert author.place is None
        self.ingest(page([], hidden=True, problems=[]))
        stat.refresh_from_db()
        assert stat.addition == before
        assert self.contest.info["problems"] == saved_problems
        assert Statistics.objects.filter(contest=self.contest).count() == 2
        assert self.contest.has_hidden_results
        assert self.contest.info["_timing_statistic_delta_seconds"] == 3600
        self.ingest(page([entry(score=123)], contest=contest(authors=[])))
        stat.refresh_from_db()
        assert stat.solving == 123
        assert not self.contest.has_hidden_results
        assert not self.contest.writers.exists()
        assert Account.objects.filter(resource=self.resource, key="c0de").exists()

    def test_history_corrects_existing_keys_without_creating_missing_results_or_clearing_others(self):
        self.ingest(page([entry()]))
        account = Account.objects.get(resource=self.resource, key="ruxwon")
        other = Contest(
            resource=self.resource,
            host=self.resource.host,
            key="other",
            title="Other",
            url=self.contest.url,
            start_time=self.contest.start_time,
            end_time=self.contest.end_time,
            duration_in_secs=3600,
        )
        Contest.objects.bulk_create([other])
        saved = Statistics.objects.create(
            account=account, resource=self.resource, contest=other, addition={"new_rating": 999, "unrelated": "keep"}
        )
        updates = {"20": {"old_rating": 10, "new_rating": 20, "rating_change": 10}, "missing": {"new_rating": 100}}
        account_update_contest_additions(account, updates, by="key")
        result = Statistics.objects.get(account=account, contest=self.contest)
        saved.refresh_from_db()
        assert result.addition["new_rating"] == 20
        assert result.addition["old_rating"] == 10
        assert result.addition["problems"]["A"]["result"] == 242
        assert saved.addition == {"new_rating": 999, "unrelated": "keep"}
        assert account.statistics_set.count() == 2
        account_update_contest_additions(account, {}, by="key")
        result.refresh_from_db()
        assert result.addition["new_rating"] == 20

    def test_personal_marathon_uses_absolute_solve_time_for_activity(self):
        solved_at = (self.contest.start_time + timedelta(hours=14, minutes=47, seconds=43)).isoformat()
        self.ingest(
            page(
                [entry(problems={"A": cell(minutes=47, time="00:47", solved_at=solved_at)})],
                contest=contest(kind="marathon", personal_minutes=120),
            )
        )
        stat = Statistics.objects.get(contest=self.contest, account__key="ruxwon")
        assert stat.last_activity == datetime.fromisoformat(solved_at)
        assert stat.account.last_activity == stat.last_activity
        assert stat.addition["problems"]["A"]["time_in_seconds"] == 47 * 60

    def test_writers_keep_exact_case_without_standings_entries(self):
        Account.objects.create(resource=self.resource, key="Alice")
        for _ in range(2):
            self.ingest(page([entry()], contest=contest(authors=["alice"])))
            assert list(self.contest.writers.values_list("key", flat=True)) == ["alice"]
            assert self.contest.info["writers"] == ["alice"]
        assert not Statistics.objects.filter(contest=self.contest, account__key="alice").exists()

    def test_writers_do_not_follow_differently_cased_renamings(self):
        Account.objects.create(resource=self.resource, key="renamed")
        AccountRenaming.objects.create(resource=self.resource, old_key="Alice", new_key="renamed")
        self.ingest(page([entry()], contest=contest(authors=["alice"])))
        assert list(self.contest.writers.values_list("key", flat=True)) == ["alice"]

    def test_default_writer_lookup_remains_case_insensitive(self):
        Account.objects.create(resource=self.resource, key="Alice")
        update_writers(self.contest, ["alice"])
        assert list(self.contest.writers.values_list("key", flat=True)) == ["Alice"]
