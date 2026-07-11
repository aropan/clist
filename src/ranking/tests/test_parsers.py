import re

from ranking.tests.parser_regression import PARSER_FIXTURES_ROOT, ParserRegressionTestCase, discover_parser_fixtures


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
