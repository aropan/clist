import ast
import copy
import logging
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from clist.models import Contest, Resource
from clist.templatetags.extras import md_url_text
from clist.tests import MIDDLEWARE_WITHOUT_DEBUG_TOOLING
from notification.models import Subscription, Task
from ranking.management.commands import parse_statistic
from ranking.management.commands.calculate_rating_prediction import ELO_MMR_RATING_FIELDS
from ranking.management.commands.parse_statistic import Command, get_standings_log_summary, log_long_operation
from ranking.management.modules.common import BaseModule
from ranking.models import Account, AccountRenaming, AccountType, Module, Statistics
from ranking.tests import test_calculate_rating_prediction
from ranking.utils import rename_account
from true_coders.models import Coder


class ParseStatisticDiagnosticsTest(SimpleTestCase):
    def test_legacy_channel_handler_and_tqdm_monkeypatch_are_removed(self):
        assert not hasattr(parse_statistic, "ChannelLayerHandler")
        assert not hasattr(parse_statistic, "_tqdm")
        assert not hasattr(parse_statistic, "async_to_sync")

    @mock.patch("ranking.management.commands.parse_statistic.threading.Timer")
    def test_long_operation_warning_contains_caller_stack(self, timer):
        logger = logging.getLogger("ranking.parse.statistic.test")

        with (
            self.assertLogs(logger, level=logging.WARNING) as logs,
            log_long_operation(logger, "Apply standings", warning_seconds=10, contest_id=123),
        ):
            timer.call_args.args[1]()

        assert "Apply standings is still running after 10 seconds" in logs.output[0]
        assert "contest_id=123" in logs.output[0]
        assert "Caller thread stack:" in logs.output[0]
        assert timer.return_value.daemon is True
        timer.return_value.start.assert_called_once_with()
        timer.return_value.cancel.assert_called_once_with()

    def test_standings_summary_only_contains_allowlisted_metadata(self):
        standings = {
            "result": {"private-user": {"token": "row-secret"}},
            "problems": [{"url": "https://example.com?api_key=problem-secret"}],
            "parsed_percentage": 68.75,
            "action": ("delete", "action-secret"),
            "cookie": "cookie-secret",
        }

        summary = get_standings_log_summary(standings)

        assert summary == "rows=1, problems=1, fields=5, parsed=68.75%, action=delete"
        assert "secret" not in summary
        assert "private-user" not in summary

    def test_unknown_standings_action_is_not_logged_verbatim(self):
        summary = get_standings_log_summary({"action": ["token=action-secret"]})

        assert summary == "rows=0, problems=0, fields=1, action=other"

    def test_parser_modules_use_live_tqdm_adapter(self):
        modules_path = Path(parse_statistic.__file__).parents[1] / "modules"
        direct_imports = []
        for path in modules_path.rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(alias.name == "tqdm" for alias in node.names):
                    direct_imports.append(str(path.relative_to(modules_path)))
                if isinstance(node, ast.ImportFrom) and node.module == "tqdm":
                    direct_imports.append(str(path.relative_to(modules_path)))

        assert direct_imports == []


class ParseStatisticConcurrencyTest(TestCase):
    def setUp(self):
        self.resource = Resource(host="concurrent-parser.example", enable=True, url="https://concurrent-parser.example")
        Resource.objects.bulk_create([self.resource])
        Module.objects.create(
            resource=self.resource,
            path="dummy.py",
            max_delay_after_end=timedelta(hours=1),
            delay_on_success=timedelta(minutes=10),
            delay_on_error=timedelta(minutes=10),
        )
        now = timezone.now()
        self.contest = Contest(
            resource=self.resource,
            title="Concurrent parser test",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            duration_in_secs=3600,
            url="https://concurrent-parser.example/contest",
            key="concurrent-parser-test",
            host=self.resource.host,
            parsed_time=now - timedelta(minutes=30),
        )
        Contest.objects.bulk_create([self.contest])

    def run_with_plugin(self, statistic_class, **kwargs):
        plugin = SimpleNamespace(Statistic=statistic_class)
        parse_kwargs = {
            "with_check": False,
            "without_subscriptions": True,
            **kwargs,
        }
        with mock.patch.object(Resource, "plugin", new_callable=mock.PropertyMock, return_value=plugin):
            return Command().parse_statistic(
                Contest.objects.filter(pk=self.contest.pk),
                **parse_kwargs,
            )

    def test_no_update_results_does_not_advance_submissions_cursor(self):
        class Statistic(BaseModule):
            def get_standings(inner_self, **kwargs):
                return {"result": {}, "submissions_info": {"last_submission_id": 10}}

        self.run_with_plugin(Statistic, no_update_results=True)

        self.contest.refresh_from_db()
        assert self.contest.submissions_info == {}
        assert not Statistics.objects.filter(contest=self.contest).exists()

    def test_completed_result_does_not_append_applied_name_override(self):
        self.contest.info["additions"] = {
            "Original Name": {"name": "Corrected Name"},
            "manual": {"member": "manual", "name": "Manual row", "place": 3, "solving": 0},
        }
        self.contest.save(update_fields=["info"])

        class Statistic(BaseModule):
            def get_standings(inner_self, **kwargs):
                result = {
                    member: {"member": member, "name": "Original Name", "place": 1, "solving": 1}
                    for member in ("first", "second")
                }
                inner_self.complete_result(result)
                return {"result": result}

        result = self.run_with_plugin(Statistic)

        assert result.status == parse_statistic.EventStatus.COMPLETED
        names = dict(Statistics.objects.filter(contest=self.contest).values_list("account__key", "addition__name"))
        assert names == {"first": "Corrected Name", "second": "Corrected Name", "manual": "Manual row"}

    def test_reparse_preserves_saved_elo_ratings_with_unchanged_standings(self):
        self.check_reparse_preserves_saved_elo_ratings()

    def test_reparse_preserves_saved_member_elo_ratings_and_fields(self):
        self.check_reparse_preserves_saved_elo_ratings(account_type="member")

    def test_reparse_restores_missing_elo_rating_additions(self):
        self.check_reparse_preserves_saved_elo_ratings(clear_rating_additions=True)

    def check_reparse_preserves_saved_elo_ratings(self, account_type=None, clear_rating_additions=False):
        Resource.objects.filter(pk=self.resource.pk).update(
            rating_prediction=test_calculate_rating_prediction.EloMmrRatingPredictionTest.rating_prediction(
                account_type=account_type
            )
        )
        places = {"first": 1, "second": 2}
        custom_field = "initial"

        class Statistic(BaseModule):
            def get_standings(inner_self, **kwargs):
                result = {
                    member: {
                        "member": member,
                        "place": place,
                        "solving": 3 - place,
                        "custom_field": custom_field,
                        "info": {"is_member": account_type == "member"},
                    }
                    for member, place in places.items()
                }
                options = {"fixed_fields": ["solving"]}
                if account_type == "member":
                    result["user"] = {"member": "user", "place": 3, "solving": 0}
                    options = {"account_type_fields": {"member": options}}
                return {"result": result, "options": options}

        previous_hash = None
        previous_timing = None
        expected_ratings = None
        with mock.patch.object(Resource, "update_icon"):
            for parse_kwargs in ({}, {"with_stats": False, "without_calculate_rating_prediction": True}, {}):
                if clear_rating_additions and expected_ratings:
                    for statistic in Statistics.objects.filter(contest=self.contest):
                        for field in ELO_MMR_RATING_FIELDS:
                            statistic.addition.pop(field, None)
                        statistic.save(update_fields=["addition"])

                result = self.run_with_plugin(Statistic, without_calculate_problem_rating=True, **parse_kwargs)
                assert result.status == parse_statistic.EventStatus.COMPLETED
                self.contest.refresh_from_db()
                ratings = {}
                for statistic in Statistics.objects.filter(contest=self.contest).select_related("account"):
                    if statistic.account.key == "user":
                        assert not any(field in statistic.addition for field in ELO_MMR_RATING_FIELDS)
                        continue
                    ratings[statistic.account.key] = {
                        field: statistic.addition[field] for field in ELO_MMR_RATING_FIELDS
                    }
                    assert statistic.account.rating == statistic.addition["new_rating"]
                    assert statistic.addition["custom_field"] == custom_field
                if previous_hash is not None:
                    assert self.contest.rating_prediction_hash == previous_hash
                    assert self.contest.rating_prediction_timing == previous_timing
                    assert ratings == expected_ratings
                previous_hash = self.contest.rating_prediction_hash
                previous_timing = self.contest.rating_prediction_timing
                expected_ratings = ratings
                assert self.contest.is_rated is True
                assert set(ELO_MMR_RATING_FIELDS) <= set(self.contest.info["fields"])
                assert all(self.contest.info["fields_types"][field] == ["int"] for field in ELO_MMR_RATING_FIELDS)
                standings = self.contest.info["standings"]
                if account_type == "member":
                    standings = standings["account_type_fields"]["member"]
                assert set(ELO_MMR_RATING_FIELDS) <= set(standings["fixed_fields"])
                assert "solving" in standings["fixed_fields"]
                custom_field = "updated"

            places.update(first=2, second=1)
            result = self.run_with_plugin(Statistic, without_calculate_problem_rating=True)

        assert result.status == parse_statistic.EventStatus.COMPLETED
        self.contest.refresh_from_db()
        assert self.contest.rating_prediction_hash != previous_hash
        assert self.contest.rating_prediction_timing != previous_timing
        for statistic in Statistics.objects.filter(contest=self.contest).select_related("account"):
            if statistic.account.key == "user":
                continue
            assert statistic.addition["new_rating"] != expected_ratings[statistic.account.key]["new_rating"]
            assert statistic.account.rating == statistic.addition["new_rating"]

    def test_changed_parsed_time_rejects_fetched_standings(self):
        changed_parsed_time = timezone.now()

        class Statistic(BaseModule):
            def get_standings(inner_self, **kwargs):
                Contest.objects.filter(pk=inner_self.contest.pk).update(parsed_time=changed_parsed_time)
                return {
                    "result": {
                        "tourist": {
                            "member": "tourist",
                            "place": 1,
                            "solving": 1,
                        }
                    }
                }

        result = self.run_with_plugin(Statistic)

        assert result.status == parse_statistic.EventStatus.WARNING
        event_log = parse_statistic.EventLog.objects.get(name="parse_statistic", object_id=self.contest.pk)
        assert "parsed_time changed" in event_log.error
        self.contest.refresh_from_db()
        assert self.contest.parsed_time == changed_parsed_time
        assert not Statistics.objects.filter(contest=self.contest).exists()

    def test_concurrent_contest_change_is_not_overwritten_after_fetch(self):
        changed_title = "Changed while standings were fetched"

        class Statistic(BaseModule):
            def get_standings(inner_self, **kwargs):
                Contest.objects.filter(pk=inner_self.contest.pk).update(title=changed_title)
                return {
                    "result": {
                        "tourist": {
                            "member": "tourist",
                            "place": 1,
                            "solving": 1,
                        }
                    }
                }

        result = self.run_with_plugin(Statistic)

        assert result.status == parse_statistic.EventStatus.COMPLETED
        self.contest.refresh_from_db()
        assert self.contest.title == changed_title
        assert Statistics.objects.filter(contest=self.contest).exists()

    def test_no_update_results_keeps_live_root_cancelled(self):
        live_event_log = parse_statistic.EventLog.objects.create(
            name="parse_statistic",
            related=self.contest,
            status=parse_statistic.EventStatus.IN_PROGRESS,
            is_live_stream=True,
        )

        class Statistic(BaseModule):
            def get_standings(inner_self, **kwargs):
                return {"result": {}}

        result = self.run_with_plugin(
            Statistic,
            live_event_log=live_event_log,
            no_update_results=True,
        )

        assert result.status == parse_statistic.EventStatus.CANCELLED
        assert result.message == "no_update_results"
        live_event_log.refresh_from_db()
        assert live_event_log.status == parse_statistic.EventStatus.CANCELLED
        assert live_event_log.message == "no_update_results"


class CompleteResultAdditionsTest(TestCase):
    def setUp(self):
        ParseStatisticConcurrencyTest.setUp(self)
        Resource.objects.filter(pk=self.resource.pk).update(host="icpc.global", has_standings_renamed_account=True)
        self.resource.refresh_from_db()
        self.contest.key = "1998"
        self.rows = {}
        self.additions = {}
        for index, name in enumerate(("First University", "Second University"), start=1):
            source = f"{name} 1997-1998"
            self.rows[source] = {
                "member": source,
                "name": name,
                "place": index,
                "solving": 3 - index,
                "problems": {"A": {"result": "+", "time": "10:00"}},
                "_members": [{"name": f"Student {index}"}],
            }
            self.additions[source] = {
                "member": f"university:{name}",
                "name": name,
                "country": "US",
                "info": {"is_university": True},
                "__update_only": True,
            }
        self.extra_standings = {}
        self.save_additions()

    def save_additions(self, complete=True):
        self.contest.info.update(additions=copy.deepcopy(self.additions), additions_complete=complete)
        self.contest.save(update_fields=["key", "info"])

    def parse(self, **kwargs):
        standings = {"result": copy.deepcopy(self.rows), **copy.deepcopy(self.extra_standings)}

        class Statistic(BaseModule):
            def get_standings(self, **kwargs):
                return standings

        with mock.patch.object(Resource, "update_icon"):
            return ParseStatisticConcurrencyTest.run_with_plugin(
                self,
                Statistic,
                without_calculate_problem_rating=True,
                without_set_coder_problems=True,
                **kwargs,
            )

    def snapshot(self):
        return {
            "accounts": list(
                Account.objects
                .filter(resource=self.resource)
                .order_by("pk")
                .values("pk", "key", "name", "country", "info", "account_type", "n_contests", "n_places", "n_writers")
            ),
            "statistics": list(
                Statistics.objects
                .filter(contest=self.contest)
                .order_by("pk")
                .values("pk", "account_id", "place", "place_as_int", "solving", "addition")
            ),
            "contest": Contest.objects.filter(pk=self.contest.pk).values("title", "info", "parsed_time").get(),
            "writers": list(self.contest.writers.order_by("pk").values_list("pk", flat=True)),
        }

    def assert_rejected(self, message):
        before = self.snapshot()
        self.extra_standings["title"] = "Must be rolled back"
        result = self.parse()
        assert result.status == parse_statistic.EventStatus.WARNING
        log = parse_statistic.EventLog.objects.filter(object_id=self.contest.pk, name="parse_statistic").latest("pk")
        assert message in log.error, log.error
        assert self.snapshot() == before

    def test_complete_additions_preserve_migrated_statistics_on_two_updates(self):
        additions = self.additions
        self.additions = {}
        self.save_additions(complete=False)
        assert self.parse().status == parse_statistic.EventStatus.COMPLETED
        original_ids = set(Statistics.objects.filter(contest=self.contest).values_list("pk", flat=True))
        self.additions = additions
        for source, addition in additions.items():
            account = Account.objects.create(
                resource=self.resource,
                key=addition["member"],
                name=addition["name"],
                country=addition["country"],
                info=addition["info"],
            )
            rename_account(Account.objects.get(resource=self.resource, key=source), account)
        self.contest.refresh_from_db()
        self.save_additions()

        previous = None
        for _ in range(2):
            assert self.parse().status == parse_statistic.EventStatus.COMPLETED
            statistics = list(Statistics.objects.filter(contest=self.contest).select_related("account"))
            assert {s.pk for s in statistics} == original_ids
            for statistic in statistics:
                account = statistic.account
                assert account.account_type == AccountType.UNIVERSITY
                source = statistic.addition["_old_key"]
                assert account.key == additions[source]["member"]
                assert statistic.addition["_members"] == self.rows[source]["_members"]
                assert statistic.addition["problems"]["A"]["result"] == "+"
                assert statistic.addition["country"] == "US"
                assert account.n_contests == 1
            current = self.snapshot()
            current.pop("contest")
            if previous is not None:
                assert current == previous
            previous = current
        assert Account.objects.filter(resource=self.resource).count() == 2

    def test_unknown_key_cannot_match_by_name_or_redirect(self):
        source = next(iter(self.rows))
        row = self.rows.pop(source)
        row.update(member="unknown", name=source)
        self.rows["unknown"] = row
        AccountRenaming.objects.create(resource=self.resource, old_key="unknown", new_key=source)
        self.assert_rejected("new keys=['unknown']")

    def test_missing_source_cannot_be_synthesized_from_additions(self):
        self.rows.pop(next(iter(self.rows)))
        self.assert_rejected("missing keys=")

    def test_empty_source_cannot_remove_existing_statistics(self):
        assert self.parse().status == parse_statistic.EventStatus.COMPLETED
        self.rows.clear()
        self.assert_rejected("missing keys=")

    def test_source_member_must_match_outer_key(self):
        next(iter(self.rows.values()))["member"] = "different member"
        self.assert_rejected("Source member differs from result key")

    def test_duplicate_targets_are_rejected_before_rekeying(self):
        first, second = self.additions.values()
        second["member"] = first["member"]
        self.save_additions()
        self.assert_rejected("Duplicate target member")

    def test_later_redirect_cannot_replace_a_target(self):
        first, second = self.additions.values()
        AccountRenaming.objects.create(resource=self.resource, old_key=first["member"], new_key=second["member"])
        self.assert_rejected("Result keys changed")

    def test_later_overrides_cannot_replace_declared_fields(self):
        for field, value in (
            ("member", "university:Unknown"),
            ("member", next(iter(self.additions.values()))["member"]),
            ("name", "Changed name"),
            ("country", "CA"),
            ("info", {"is_university": False}),
        ):
            with self.subTest(field=field, value=value):
                self.contest.info["parse"] = {"addition": {field: value}}
                self.contest.save(update_fields=["info"])
                self.assert_rejected(f"field={field}")

    def test_later_modifiers_cannot_change_declared_targets(self):
        self.contest.info["standings"] = {"modifiers": [{"field": "member", "regex": r"^(?P<value>.*) University$"}]}
        self.contest.save(update_fields=["info"])
        self.assert_rejected("field=member")

    def test_standings_filters_cannot_hide_missing_rows(self):
        for regex in ("First", "No matching teams"):
            with self.subTest(regex=regex):
                self.contest.info["standings"] = {"filters": [{"field": "name", "regex": regex}]}
                self.contest.save(update_fields=["info"])
                self.assert_rejected("Result keys changed")

    def test_actions_cannot_delete_approved_accounts_or_contest(self):
        self.extra_standings["action"] = "delete"
        self.assert_rejected("Standings action conflicts")
        self.extra_standings.pop("action")
        self.contest.info["parse"] = {"addition": {"action": "delete"}}
        self.contest.save(update_fields=["info"])
        self.assert_rejected("Account action conflicts")

    def test_incomplete_configuration_does_not_enable_an_empty_allowlist(self):
        self.additions.clear()
        self.save_additions()
        self.assert_rejected("requires nonempty additions")

    def test_flag_works_on_another_resource(self):
        Resource.objects.filter(pk=self.resource.pk).update(host="another-resource.example")
        assert self.parse().status == parse_statistic.EventStatus.COMPLETED
        self.rows["other"] = {"member": "other", "place": 3, "solving": 0}
        self.assert_rejected("new keys=['other']")

    def test_another_resource_without_flag_keeps_existing_behavior(self):
        Resource.objects.filter(pk=self.resource.pk).update(host="another-resource.example")
        self.save_additions(complete=False)
        self.rows["other"] = {"member": "other", "place": 3, "solving": 0}
        assert self.parse().status == parse_statistic.EventStatus.COMPLETED
        assert Statistics.objects.filter(contest=self.contest, account__key="other").exists()

    def test_writers_are_updated_when_results_update_is_disabled(self):
        self.extra_standings["writers"] = ["author"]

        self.parse(no_update_results=True)

        assert list(self.contest.writers.values_list("key", flat=True)) == ["author"]
        assert not Statistics.objects.filter(contest=self.contest).exists()

    def test_writer_updates_are_rolled_back_on_later_addition_conflict(self):
        self.extra_standings["writers"] = ["author"]
        self.contest.info["parse"] = {"addition": {"country": "CA"}}
        self.contest.save(update_fields=["info"])

        with mock.patch.object(
            parse_statistic, "update_writers", wraps=parse_statistic.update_writers
        ) as update_writers:
            self.assert_rejected("field=country")

        update_writers.assert_called_once()

    def test_unflagged_finals_and_regionals_keep_existing_behavior(self):
        for key in ("1985", "1999", "2025", "1998 regional"):
            with self.subTest(key=key):
                self.contest.refresh_from_db()
                self.contest.key = key
                self.save_additions(complete=False)
                self.rows["other"] = {"member": "other", "place": 3, "solving": 0}
                assert self.parse().status == parse_statistic.EventStatus.COMPLETED
                assert Statistics.objects.filter(contest=self.contest, account__key="other").exists()

    @override_settings(MIDDLEWARE=MIDDLEWARE_WITHOUT_DEBUG_TOOLING)
    def test_celebrity_remains_user_without_place_after_two_updates(self):
        for year, name in (("1988", "Celebrity Team"), ("1989", "Celebrity")):
            with self.subTest(year=year):
                source = f"{name} {int(year) - 1}-{year}"
                self.contest.refresh_from_db()
                self.contest.key = year
                self.rows[source] = {"member": source, "name": name, "place": 0, "solving": 10}
                self.additions[source] = {"member": source, "name": name, "place": None, "__update_only": True}
                self.save_additions()
                for _ in range(2):
                    assert self.parse().status == parse_statistic.EventStatus.COMPLETED
                    statistics = self.contest.statistics_set.order_by(*self.contest.get_statistics_order())
                    celebrity = statistics.get(account__key=source)
                    assert celebrity.place is None
                    assert celebrity.place_as_int is None
                    assert celebrity.account.account_type == AccountType.USER
                    assert not celebrity.account.info.get("is_university")
                    assert not celebrity.account.n_places
                    assert list(statistics.values_list("account__key", flat=True))[-1] == source
                response = self.client.get(f"/standings/{self.contest.pk}/", follow=True)
                assert response.status_code == 200
                assert list(response.context["statistics"])[-1].account.key == source
                self.contest.info["parse"] = {"addition": {"place": 0}}
                self.contest.save(update_fields=["info"])
                self.assert_rejected("field=place")
                self.contest.info.pop("parse")
                self.contest.save(update_fields=["info"])
                self.rows.pop(source)
                self.additions.pop(source)


CUSTOM_MESSAGES = [{"type": "league_change", "message": "{account} moved to `Bronze` league. {contest}"}]


class CustomSubscriptionMessagesParseTest(TestCase):
    def setUp(self):
        ParseStatisticConcurrencyTest.setUp(self)
        self.coder = Coder.objects.create(username="subscriber")
        self.account = Account.objects.create(resource=self.resource, key="player")

    def subscribe(self, method="telegram:100", **fields):
        subscription = Subscription.objects.create(coder=self.coder, method=method, **fields)
        return subscription

    def parse(self, **row):
        rows = {"player": {"member": "player", "place": 1, "solving": 10, **row}}

        class Statistic(BaseModule):
            def get_standings(inner_self, **kwargs):
                return {"result": copy.deepcopy(rows)}

        return ParseStatisticConcurrencyTest.run_with_plugin(self, Statistic, without_subscriptions=False)

    def sent_messages(self):
        return list(Task.objects.filter(message__isnull=False).values_list("message", flat=True))

    def test_row_without_custom_messages_does_not_send_anything(self):
        self.subscribe().accounts.add(self.account)

        self.parse()

        assert self.sent_messages() == []

    def test_skip_subscription_row_does_not_send_anything(self):
        self.subscribe().accounts.add(self.account)

        self.parse(_subscription_messages=CUSTOM_MESSAGES, _skip_subscription=True)

        assert self.sent_messages() == []

    def test_recipient_matched_twice_gets_single_message(self):
        self.subscribe().accounts.add(self.account)
        self.subscribe(top_n=10)

        self.parse(_subscription_messages=CUSTOM_MESSAGES)

        assert len(self.sent_messages()) == 1

    def test_top_n_subscriber_receives_message(self):
        other_coder = Coder.objects.create(username="top-watcher")
        Subscription.objects.create(coder=other_coder, method="telegram:200", top_n=10)

        self.parse(_subscription_messages=CUSTOM_MESSAGES)

        assert len(self.sent_messages()) == 1

    def test_message_is_sent_with_rendered_links(self):
        self.subscribe().accounts.add(self.account)

        self.parse(_subscription_messages=CUSTOM_MESSAGES)

        statistic = Statistics.objects.get(contest=self.contest, account=self.account)
        (message,) = self.sent_messages()
        assert f"/standings/{self.contest.pk}/?find_me={statistic.pk}" in message
        assert "moved to `Bronze` league." in message
        assert md_url_text(self.contest.title) in message
        assert "{" not in message
        assert "}" not in message

    def test_subscription_excluded_by_base_filter_does_not_compose_message(self):
        subscription = self.subscribe(exclude_contest=self.contest)
        subscription.accounts.add(self.account)

        target = "ranking.management.commands.parse_statistic.compose_message_by_custom_messages"
        with mock.patch(target) as compose:
            self.parse(_subscription_messages=CUSTOM_MESSAGES)

        compose.assert_not_called()
        assert self.sent_messages() == []

    def test_message_of_previous_parse_is_not_carried_over(self):
        self.subscribe().accounts.add(self.account)

        self.parse(_subscription_messages=CUSTOM_MESSAGES)
        assert len(self.sent_messages()) == 1

        self.parse()

        statistic = Statistics.objects.get(contest=self.contest, account=self.account)
        assert "_subscription_messages" not in statistic.addition
        assert len(self.sent_messages()) == 1

    def test_custom_messages_are_stored_as_a_special_addition_field(self):
        self.subscribe().accounts.add(self.account)

        self.parse(_subscription_messages=CUSTOM_MESSAGES)

        statistic = Statistics.objects.get(contest=self.contest, account=self.account)
        assert statistic.addition["_subscription_messages"] == CUSTOM_MESSAGES
        assert Statistics.is_special_addition_field("_subscription_messages")
