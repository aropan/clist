from collections import OrderedDict
from types import SimpleNamespace

from django.test import SimpleTestCase

from ranking.management.modules.common import BaseModule, apply_result_additions


class DummyModule(BaseModule):
    def get_standings(self, **kwargs):
        return {}


class ApplyResultAdditionsTest(SimpleTestCase):
    def test_missing_contest_or_info_is_ignored(self):
        result = {"member": {"member": "member"}}

        apply_result_additions(None, result)
        apply_result_additions(SimpleNamespace(info=None), result)

        assert result == {"member": {"member": "member"}}

    def test_complete_result_without_contest_uses_module_info(self):
        module = DummyModule(info={"additions": {"Original Name": {"name": "Updated Name"}}})
        result = {"member": {"member": "member", "name": "Original Name"}}

        module.complete_result(result)

        assert result["member"]["name"] == "Updated Name"

    def test_complete_result_without_contest_or_info_is_ignored(self):
        result = {"member": {"member": "member"}}

        DummyModule().complete_result(result)

        assert result == {"member": {"member": "member"}}

    def test_matches_member_and_original_name_then_adds_missing_rows(self):
        contest = SimpleNamespace(
            info={
                "additions": {
                    "old-member": {"name": "Updated Name", "member_value": 1},
                    "Original Name": {"name_value": 2},
                    "new-member": {"member": "new-member", "name": "New Member"},
                    "update-only": {"member": "update-only", "__update_only": True},
                }
            }
        )
        result = {
            "old-member": {
                "member": "old-member",
                "name": "Original Name",
            }
        }

        apply_result_additions(contest, result, add_missing=True)

        assert result == {
            "old-member": {
                "member": "old-member",
                "name": "Updated Name",
                "member_value": 1,
                "name_value": 2,
            },
            "new-member": {"member": "new-member", "name": "New Member"},
        }
        assert contest.info["additions"] == {
            "old-member": {"name": "Updated Name", "member_value": 1},
            "Original Name": {"name_value": 2},
            "new-member": {"member": "new-member", "name": "New Member"},
            "update-only": {"member": "update-only", "__update_only": True},
        }

    def test_early_application_matches_name_only_and_updates_duplicate_names(self):
        contest = SimpleNamespace(
            info={
                "additions": {
                    "member-1": {"matched_by_member": True},
                    "Team Name": OrderedDict((("second", 2), ("first", 1))),
                    "missing": {"member": "missing"},
                }
            }
        )
        result = {
            "member-1": {"member": "member-1", "name": "Team Name"},
            "member-2": {"member": "member-2", "name": "Team Name"},
        }

        apply_result_additions(contest, result, match_fields=("name",))

        assert result == {
            "member-1": {"member": "member-1", "name": "Team Name", "second": 2, "first": 1},
            "member-2": {"member": "member-2", "name": "Team Name", "second": 2, "first": 1},
        }
        assert list(result["member-1"])[-2:] == ["second", "first"]
        assert contest.info["additions"]["Team Name"] == {"second": 2, "first": 1}
