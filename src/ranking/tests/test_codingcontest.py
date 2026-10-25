from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from ranking.management.modules.codingcontest import Statistic
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse
from ranking.tests.parser_fixture_command import Command


def entry(name="Coder", **changes):
    return {
        "rank": 1,
        "playerName": name,
        "teamName": None,
        "isSolo": True,
        "level": 5,
        "score": None,
        "displayScore": "5 levels",
        "timeMs": 13330445,
        "venueName": "Online",
        "venueCity": None,
        "isYou": False,
    } | changes


def page(rows, number=0, size=100, total=None):
    total = len(rows) if total is None else total
    return {
        "content": rows,
        "page": number,
        "size": size,
        "totalPages": (total + size - 1) // size,
        "totalElements": total,
    }


class CodingContestTestCase(SimpleTestCase):
    def setUp(self):
        self.module = Statistic(key="37", resource=SimpleNamespace(url="https://codingcontest.org/"))
        self.request_get = self.enterContext(mock.patch("ranking.management.modules.codingcontest.REQ.get"))

    def parse_rows(self, *rows):
        self.request_get.return_value = page(list(rows))
        return list(self.module.get_standings()["result"].values())


class CodingContestPaginationTests(CodingContestTestCase):
    def test_all_pages_include_zero_results_and_shared_ranks(self):
        self.request_get.side_effect = [
            page([entry("First"), entry("Second", rank=2)], size=2, total=5),
            page([entry("Third", rank=3), entry("Fourth", rank=4, level=0, timeMs=0)], number=1, size=2, total=5),
            page([entry("Fifth", rank=4, level=0, timeMs=0)], number=2, size=2, total=5),
        ]

        rows = list(self.module.get_standings()["result"].values())

        assert [row["name"] for row in rows] == ["First", "Second", "Third", "Fourth", "Fifth"]
        assert [row["place"] for row in rows] == [1, 2, 3, 4, 4]
        assert [row["solving"] for row in rows] == [5, 5, 5, 0, 0]
        assert self.request_get.call_args_list == [
            mock.call(
                f"https://codingcontest.org/api/hall-of-fame/contests/37/leaderboard?page={p}&size=100",
                return_json=True,
            )
            for p in range(3)
        ]

    def test_valid_empty_tables(self):
        for total_pages in (0, 1):
            with self.subTest(total_pages=total_pages):
                self.request_get.return_value = page([]) | {"totalPages": total_pages}
                assert self.module.get_standings()["result"] == {}

    def test_malformed_envelopes_fail(self):
        valid = page([entry()])
        invalid = [None, [], "not JSON", {}]
        invalid.extend(valid | {"content": value} for value in (None, {}, "rows"))
        for field in ("page", "size", "totalPages", "totalElements"):
            invalid.extend(valid | {field: value} for value in (None, -1, "1", True))
            invalid.append({key: value for key, value in valid.items() if key != field})
        invalid.extend([valid | {"page": 1}, valid | {"size": 0}])
        for response in invalid:
            with self.subTest(response=response):
                self.request_get.return_value = response
                with self.assertRaisesMessage(ExceptionParseStandings, "page=0"):
                    self.module.get_standings()

    def test_incomplete_pagination_fails(self):
        for response in (
            page([entry()], total=2),
            page([entry()]) | {"totalPages": 0},
            page([entry()]) | {"totalPages": 2},
            page([]) | {"totalPages": 2},
        ):
            with self.subTest(response=response):
                self.request_get.return_value = response
                with self.assertRaisesMessage(ExceptionParseStandings, "Incomplete pagination"):
                    self.module.get_standings()

    def test_repeated_changed_and_missing_later_pages_fail(self):
        first = page([entry("First")], size=1, total=2)
        second = page([entry("Second")], number=1, size=1, total=2)
        for response in (
            second | {"page": 0},
            second | {"totalPages": 3, "totalElements": 3},
            second | {"size": 2},
            second | {"content": []},
        ):
            with self.subTest(response=response):
                self.request_get.side_effect = [first, response]
                with self.assertRaisesMessage(ExceptionParseStandings, "page=1"):
                    self.module.get_standings()

    def test_http_and_json_failures_do_not_return_partial_results(self):
        for error in (FailOnGetResponse("unavailable"), ValueError("invalid JSON")):
            with self.subTest(error=error):
                self.request_get.side_effect = [page([entry()], size=1, total=2), error]
                with self.assertRaisesMessage(ExceptionParseStandings, "page=1"):
                    self.module.get_standings()

    def test_invalid_contest_key_does_not_make_requests(self):
        for key in ("37/game", "legacy-key", "٣٧"):
            with self.subTest(key=key):
                self.module.key = key
                with self.assertRaisesMessage(ExceptionParseStandings, "numeric contest key"):
                    self.module.get_standings()
        self.request_get.assert_not_called()


class CodingContestResultTests(CodingContestTestCase):
    def test_level_results_keep_source_places_and_context(self):
        rows = self.parse_rows(
            entry("Team", rank=7, isSolo=False, teamName="Team", venueName="FSEGA", venueCity="Cluj-Napoca"),
            entry("Zero", rank=12, level=0, timeMs=0, displayScore="0 levels"),
            entry("Another zero", rank=12, level=0, timeMs=0),
        )

        team, zero, another_zero = rows
        assert team["name"] == "Team"
        assert team["place"] == 7
        assert team["solving"] == team["level"] == 5
        assert team["mode"] == "Team"
        assert team["team_name"] == "Team"
        assert team["venue"] == "FSEGA"
        assert team["city"] == "Cluj-Napoca"
        assert team["time"] == "3:42:10"
        assert team["time_ms"] == 13330445
        assert team["display_score"] == "5 levels"
        assert zero["solving"] == another_zero["solving"] == 0
        assert zero["place"] == another_zero["place"] == 12
        assert zero["time"] == "0:00:00"
        assert zero["time_ms"] == 0
        assert "city" not in zero

    def test_numeric_scores_including_zero_are_not_replaced_with_levels(self):
        for score in (0, 3099, -1, 12.5):
            with self.subTest(score=score):
                (row,) = self.parse_rows(entry(score=score, level=4, displayScore="-"))
                assert row["solving"] == score
                assert row["level"] == 4
                assert row["display_score"] == "-"

    def test_source_rank_is_not_recomputed_from_score(self):
        rows = self.parse_rows(
            entry("Higher level", rank=1, level=4, score=0), entry("Lower level", rank=2, level=3, score=50)
        )

        assert [(row["place"], row["solving"]) for row in rows] == [(1, 0), (2, 50)]

    def test_solo_team_name_optional_metadata_and_long_elapsed_time(self):
        self.module.start_time = 0
        self.module.end_time = 4 * 3600
        (row,) = self.parse_rows(entry(teamName="Single person", timeMs=15880069, displayScore=None))

        assert row["mode"] == "Solo"
        assert row["team_name"] == "Single person"
        assert row["time"] == "4:24:40"
        assert row["time_ms"] == 15880069
        assert "display_score" not in row
        assert "city" not in row
        assert "problems" not in row
        assert "_members" not in row

    def test_invalid_rows_fail_with_contest_and_page_context(self):
        invalid = [None, [], {}]
        for field in ("rank", "playerName", "isSolo", "level", "score", "timeMs", "venueName"):
            invalid.append({key: value for key, value in entry().items() if key != field})
        for field in ("rank", "level", "timeMs"):
            invalid.extend(entry(**{field: value}) for value in (None, -1, "1", True, 1.5))
        invalid.append(entry(rank=0))
        for field in ("playerName", "venueName"):
            invalid.extend(entry(**{field: value}) for value in (None, 1, "", "  "))
        invalid.extend(entry(isSolo=value) for value in (None, 0, "true"))
        invalid.extend(entry(score=value) for value in (True, "1", float("nan"), float("inf")))
        for field in ("teamName", "venueCity", "displayScore"):
            invalid.extend(entry(**{field: value}) for value in (1, []))
        for row in invalid:
            with self.subTest(row=row):
                self.request_get.return_value = page([row])
                with self.assertRaisesMessage(ExceptionParseStandings, "contest 37, page 0"):
                    self.module.get_standings()


class CodingContestIdentityTests(CodingContestTestCase):
    def test_adjacent_contests_do_not_share_identities(self):
        self.module.info = {"parse": {"editionName": "Same edition"}}
        (first,) = self.parse_rows(entry())
        self.module.key = "38"
        (second,) = self.parse_rows(entry())

        assert first["member"].startswith("37:")
        assert second["member"].startswith("38:")
        assert first["member"] != second["member"]

    def test_mode_venue_and_city_distinguish_equal_names(self):
        rows = self.parse_rows(
            entry("Castravete"),
            entry("Castravete", isSolo=False),
            entry("Castravete", venueName="FSEGA"),
            entry("Castravete", venueName="FSEGA", venueCity="Cluj-Napoca"),
        )

        assert len({row["member"] for row in rows}) == 4

    def test_result_changes_do_not_change_identity(self):
        (first,) = self.parse_rows(entry())
        (second,) = self.parse_rows(entry(rank=42, level=7, score=0, timeMs=15880069, displayScore="-", isYou=True))

        assert first["member"] == second["member"]
        assert first["place"] != second["place"]
        assert first["solving"] != second["solving"]

    def test_page_position_and_order_do_not_change_identity(self):
        self.request_get.side_effect = [
            page([entry("First")], size=1, total=2),
            page([entry("Second")], number=1, size=1, total=2),
        ]
        first = self.module.get_standings()["result"]
        self.request_get.side_effect = [
            page([entry("Second")], size=1, total=2),
            page([entry("First")], number=1, size=1, total=2),
        ]

        assert self.module.get_standings()["result"] == first

    def test_readable_parts_transliterate_names_and_preserve_boundaries(self):
        rows = self.parse_rows(
            entry("Кубок"),
            entry("кубок"),
            entry("a:b", venueName="c"),
            entry("a", venueName="b:c"),
            entry("Jörg Øresund Straße", venueName="Școală", venueCity="Łódź"),
        )

        assert len({row["member"] for row in rows}) == 5
        members = {row["name"]: row["member"] for row in rows}
        assert members["Кубок"] == "37:kubok:solo:online:-"
        assert members["кубок"] == "37:kubok:solo:online:-:1"
        assert members["a:b"].split(":") == ["37", "a-b", "solo", "c"]
        assert members["a"].split(":") == ["37", "a", "solo", "b-c"]
        assert members["Jörg Øresund Straße"] == "37:jorg-oresund-strasse:solo:scoala:lodz"

    def test_punctuation_becomes_single_hyphens_without_trailing_separators(self):
        rows = self.parse_rows(
            entry("-- Alice..+@example.com / ", venueName=" : Online___venue--- ", venueCity=" Łódź / Poland!"),
            entry("a" * 99 + ":suffix"),
        )

        assert rows[0]["member"] == "37:alice-example-com:solo:online___venue:lodz-poland"
        assert rows[1]["member"] == "37:" + "a" * 50 + "…" + "a" * 43 + "-suffix:solo:online"

    def test_middle_trimming_keeps_long_parts_bounded_and_preserves_both_ends(self):
        name = "a" * 390
        rows = self.parse_rows(
            entry(name + "A", venueName="Л" * 390, venueCity="é" * 390),
            entry(name + "B", venueName="Л" * 390, venueCity="é" * 390),
        )

        assert all(len(row["member"]) < 400 for row in rows)
        parts = [row["member"].split(":") for row in rows]
        assert parts[0][1] == "a" * 50 + "…" + "a" * 50
        assert parts[1][1] == "a" * 50 + "…" + "a" * 49 + "b"
        assert all(len(part) <= 101 for row in parts for part in row)
        assert [row["name"] for row in rows] == [name + "A", name + "B"]

    def test_middle_trimming_collisions_get_suffixes(self):
        names = ["a" * 60 + middle + "z" * 60 for middle in ("First", "Second")]
        rows = self.parse_rows(*(entry(name) for name in names))

        assert rows[0]["member"] == "37:" + "a" * 50 + "…" + "z" * 50 + ":solo:online:-"
        assert rows[1]["member"] == rows[0]["member"] + ":1"
        assert [row["name"] for row in rows] == names

    def test_empty_slugs_use_placeholders(self):
        (row,) = self.parse_rows(entry("🎯", venueName="✨"))

        assert row["member"].split(":") == ["37", "-", "solo", "-"]
        assert row["name"] == "🎯"

    def test_collision_suffix_cannot_be_confused_with_a_numeric_city(self):
        rows = self.parse_rows(entry("X"), entry("x"), entry("x", venueCity="1"))

        assert {row["member"] for row in rows} == {
            "37:x:solo:online:-",
            "37:x:solo:online:-:1",
            "37:x:solo:online:1",
        }

    def test_missing_and_null_optional_city_share_an_identity(self):
        (first,) = self.parse_rows(entry())
        (second,) = self.parse_rows({key: value for key, value in entry().items() if key != "venueCity"})

        assert first["member"] == second["member"] == "37:coder:solo:online"

    def test_duplicate_identities_across_pages_get_numbered_keys(self):
        self.request_get.side_effect = [
            page([entry()], size=1, total=2),
            page([entry(rank=2, score=0)], number=1, size=1, total=2),
        ]

        result = self.module.get_standings()["result"]

        assert list(result) == ["37:coder:solo:online:-", "37:coder:solo:online:-:1"]
        assert [row["place"] for row in result.values()] == [1, 2]
        assert [row["solving"] for row in result.values()] == [5, 0]

    def test_normalized_collisions_keep_keys_when_ranks_and_page_order_change(self):
        self.request_get.side_effect = [
            page([entry("John")], size=1, total=2),
            page([entry("Jöhn", rank=2)], number=1, size=1, total=2),
        ]
        first = {row["name"]: member for member, row in self.module.get_standings()["result"].items()}
        self.request_get.side_effect = [
            page([entry("Jöhn")], size=1, total=2),
            page([entry("John", rank=2)], number=1, size=1, total=2),
        ]
        second = {row["name"]: member for member, row in self.module.get_standings()["result"].items()}

        assert first == second == {"John": "37:john:solo:online:-", "Jöhn": "37:john:solo:online:-:1"}


class CodingContestSelectionTests(CodingContestTestCase):
    def test_contact_like_public_names_keep_their_keys_after_fixture_sanitization(self):
        response = page([entry("alice@example.com"), entry("+1234567890")])
        self.request_get.return_value = response
        result = self.module.get_standings()["result"]
        self.request_get.return_value = Command().sanitize_fixture_data(response)

        assert self.module.get_standings(users=list(result))["result"] == result

    def test_selected_users_are_filtered_after_all_pages_are_fetched(self):
        (selected,) = self.parse_rows(entry("Second"))
        self.request_get.reset_mock()
        self.request_get.side_effect = [
            page([entry("First")], size=1, total=2),
            page([entry("Second")], number=1, size=1, total=2),
        ]

        result = self.module.get_standings(users=[selected["member"]])["result"]

        assert result == {selected["member"]: selected}
        assert self.request_get.call_count == 2
        assert all("search=" not in call.args[0] for call in self.request_get.call_args_list)

    def test_empty_or_name_only_selection_does_not_match_account_keys(self):
        self.request_get.return_value = page([entry()])
        for users in ([], ["Coder"], ["38:another-contest"]):
            with self.subTest(users=users):
                assert self.module.get_standings(users=users)["result"] == {}

    def test_unselected_rows_are_still_validated_for_errors(self):
        self.request_get.return_value = page([entry(), entry("Invalid", level=None)])

        with self.assertRaisesMessage(ExceptionParseStandings, "Invalid level"):
            self.module.get_standings(users=[])

    def test_selection_keeps_the_collision_suffix_from_the_complete_table(self):
        rows = self.parse_rows(entry("John"), entry("JOHN"))
        selected = next(row for row in rows if row["name"] == "John")

        assert selected["member"].endswith(":1")
        assert self.module.get_standings(users=[selected["member"]])["result"] == {selected["member"]: selected}

    def test_account_flags_follow_mode_without_invented_profiles_or_problems(self):
        self.request_get.return_value = page([entry(teamName="One person", isYou=True), entry("Team", isSolo=False)])
        standings = self.module.get_standings()
        solo, team = standings["result"].values()

        assert solo["info"] == {"is_team": False, "_no_profile_url": True}
        assert team["info"] == {"is_team": True, "_no_profile_url": True}
        assert standings["fixed_fields"] == ["time"]
        assert standings["hidden_fields"] == ["time_ms", "display_score", "team_name", "venue", "city"]
        assert "problems" not in standings
        assert "season" not in standings
        for row in (solo, team):
            for field in ("isYou", "_members", "problems", "profile_url", "country"):
                assert field not in row

    def test_resource_origin_is_used_without_replacing_contest_urls_or_metadata(self):
        self.module.resource.url = "https://contests.example/base/"
        self.module.url = "https://register.example/old-listing"
        self.module.info = {"parse": {"id": 37}}
        self.request_get.return_value = page([entry()])

        standings = self.module.get_standings()

        self.request_get.assert_called_once_with(
            "https://contests.example/api/hall-of-fame/contests/37/leaderboard?page=0&size=100",
            return_json=True,
        )
        assert "url" not in standings
        assert "contest_url" not in standings
        assert self.module.url == "https://register.example/old-listing"
        assert self.module.info == {"parse": {"id": 37}}
