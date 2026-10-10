import re

from django.test import SimpleTestCase

from ranking.tests.parser_regression import (
    PARSER_FIXTURES_LFS_PULL,
    PARSER_FIXTURES_ROOT,
    ParserRegressionTestCase,
    discover_parser_fixtures,
    parser_fixture_inventory_problems,
)


class ParserFixtureInventoryTests(SimpleTestCase):
    def test_fixtures_are_complete_and_materialized(self):
        problems = parser_fixture_inventory_problems()
        assert not problems, "\n".join([
            "Parser fixtures are incomplete or not fetched from Git LFS:",
            *(f"  {problem}" for problem in problems),
            f"Fetch the archives with: {PARSER_FIXTURES_LFS_PULL}",
        ])

        fixture_paths = {db_path.parent for db_path in PARSER_FIXTURES_ROOT.rglob("db.json")}
        assert len(discover_parser_fixtures()) == len(fixture_paths)


class ParserRegressionTests(ParserRegressionTestCase):
    pass


def _test_name(fixture_path):
    relative_path = fixture_path.relative_to(PARSER_FIXTURES_ROOT).as_posix()
    return "test_" + re.sub(r"\W+", "_", relative_path).strip("_").lower()


def _make_test(fixture_path):
    def test(self):
        self.run_fixture(fixture_path)

    test.__name__ = _test_name(fixture_path)
    test.__doc__ = f"Replay parser fixture {fixture_path.relative_to(PARSER_FIXTURES_ROOT)}"
    return test


for parser_fixture in discover_parser_fixtures():
    setattr(ParserRegressionTests, _test_name(parser_fixture), _make_test(parser_fixture))
