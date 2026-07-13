from django.test import SimpleTestCase
from rq.job import validate_job_id

from utils.rq import get_resource_job_id
from utils.strings import split_team_name_and_members


class GetResourceJobIdTest(SimpleTestCase):
    def test_dotted_host_is_valid_job_id(self):
        job_id = get_resource_job_id("parse_statistics", "codeforces.com")
        validate_job_id(job_id)
        assert job_id == "parse_statistics_codeforces-com"

    def test_host_with_path_is_valid_job_id(self):
        job_id = get_resource_job_id("parse_accounts", "nerc.itmo.ru/school")
        validate_job_id(job_id)
        assert job_id == "parse_accounts_nerc-itmo-ru-school"


class SplitTeamNameAndMembersTest(SimpleTestCase):
    def test_splits_plain_members(self):
        assert split_team_name_and_members("Team (Alice, Bob)") == ("Team", ["Alice", "Bob"])

    def test_allows_one_level_parentheses_in_members(self):
        assert split_team_name_and_members("Team (Alice (coach), Bob)") == ("Team", ["Alice (coach)", "Bob"])

    def test_uses_last_parenthesized_group(self):
        assert split_team_name_and_members("Team (old) (Alice, Bob)") == ("Team (old)", ["Alice", "Bob"])

    def test_rejects_nested_parentheses_in_members(self):
        assert split_team_name_and_members("Team (((Alice)))") is None

    def test_rejects_missing_members_group(self):
        assert split_team_name_and_members("Team") is None

    def test_allows_trailing_whitespace(self):
        assert split_team_name_and_members("Team (Alice, Bob)  ") == ("Team", ["Alice", "Bob"])

    def test_does_not_split_commas_inside_member_parentheses(self):
        assert split_team_name_and_members("Team (Alice (coach, captain), Bob)") == (
            "Team",
            ["Alice (coach, captain)", "Bob"],
        )

    def test_returns_no_members_for_empty_parentheses(self):
        assert split_team_name_and_members("Team ()") == ("Team", [])
