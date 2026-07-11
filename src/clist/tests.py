import json
import os
import tempfile
from unittest import mock

import pytest
import yaml
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from clist.models import Resource


class CheckScheduleParsingTestCase(TestCase):
    def setUp(self):
        # Resource.save() fetches the favicon over the network when icon_file is empty
        patcher = mock.patch.object(Resource, "update_icon")
        patcher.start()
        self.addCleanup(patcher.stop)

        self.now = timezone.now()
        # Create an enabled resource
        self.enabled_resource = Resource.objects.create(
            host="enabled.example.com",
            enable=True,
            url="https://enabled.example.com/",
        )
        # Create a disabled resource
        self.disabled_resource = Resource.objects.create(
            host="disabled.example.com",
            enable=False,
            url="https://disabled.example.com/",
        )

        # Create temporary files
        self.temp_dir = tempfile.TemporaryDirectory()
        self.stats_file = os.path.join(self.temp_dir.name, "stats.json")
        self.cache_file = os.path.join(self.temp_dir.name, "cache.yaml")

        # Set up a dummy stats JSON
        self.stats_data = {
            "finished_at": int(self.now.timestamp()),
            "resources": [
                {
                    "rid": self.enabled_resource.pk,
                    "host": self.enabled_resource.host,
                    "n_contests_parsed": 10,
                    "n_contests_upserted": 2,
                },
                {
                    "rid": self.disabled_resource.pk,
                    "host": self.disabled_resource.host,
                    "n_contests_parsed": 5,
                    "n_contests_upserted": 0,
                },
            ],
        }
        with open(self.stats_file, "w", encoding="utf-8") as f:
            json.dump(self.stats_data, f)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_run_command_success(self):
        # Running the command with dryrun
        call_command(
            "check_schedule_parsing",
            stats_file=self.stats_file,
            cache_file=self.cache_file,
            dryrun=True,
        )
        # Verify that cache file was NOT written in dryrun
        assert not os.path.exists(self.cache_file)

    def test_run_command_saves_cache_atomically(self):
        # Running without dryrun
        call_command(
            "check_schedule_parsing",
            stats_file=self.stats_file,
            cache_file=self.cache_file,
        )
        # Verify cache file exists
        assert os.path.exists(self.cache_file)
        with open(self.cache_file, encoding="utf-8") as f:
            cache = yaml.safe_load(f)
        assert "resources" in cache

    def test_run_command_with_invalid_host(self):
        # Passing an invalid host should raise CommandError
        with pytest.raises(CommandError):
            call_command(
                "check_schedule_parsing",
                stats_file=self.stats_file,
                cache_file=self.cache_file,
                resources=["nonexistent.example.com"],
                dryrun=True,
            )

    def test_run_command_filters_disabled_resource(self):
        # Run command with dryrun=False
        call_command(
            "check_schedule_parsing",
            stats_file=self.stats_file,
            cache_file=self.cache_file,
        )
        # Load cache
        with open(self.cache_file, encoding="utf-8") as f:
            cache = yaml.safe_load(f)
        resources_cache = cache["resources"]
        # Enabled resource should be present in cache
        assert self.enabled_resource.pk in resources_cache
        # Disabled resource should NOT be in cache because it was skipped during checking
        assert self.disabled_resource.pk not in resources_cache

    def _write_stats(self):
        with open(self.stats_file, "w", encoding="utf-8") as f:
            json.dump(self.stats_data, f)

    def _seed_cache(self, resource_state):
        state = {"resources": {self.enabled_resource.pk: resource_state}}
        with open(self.cache_file, "w", encoding="utf-8") as f:
            yaml.dump(state, f)

    def _call_with_logs(self):
        with self.assertLogs("clist.check_schedule_parsing", level="WARNING") as logs:
            call_command(
                "check_schedule_parsing",
                stats_file=self.stats_file,
                cache_file=self.cache_file,
                dryrun=True,
            )
        return logs.output

    def test_alert_on_stale_stats(self):
        self.stats_data["finished_at"] = int(self.now.timestamp()) - 24 * 60 * 60
        self._write_stats()
        output = self._call_with_logs()
        assert any("last schedule update finished" in line for line in output)

    def test_alert_on_zero_parsed_recently_active(self):
        self._seed_cache({"last_nonzero_at": int(self.now.timestamp())})
        self.stats_data["resources"][0]["n_contests_parsed"] = 0
        self._write_stats()
        output = self._call_with_logs()
        assert any("enabled.example.com: no contests parsed" in line for line in output)

    def test_no_alert_on_zero_parsed_long_inactive(self):
        self._seed_cache({"last_nonzero_at": int(self.now.timestamp()) - 30 * 24 * 60 * 60})
        self.stats_data["resources"][0]["n_contests_parsed"] = 0
        self._write_stats()
        with pytest.raises(AssertionError):  # no warnings expected
            self._call_with_logs()

    def test_alert_on_parsed_but_not_upserted(self):
        self._seed_cache({"last_upserted_at": int(self.now.timestamp())})
        self.stats_data["resources"][0]["n_contests_upserted"] = 0
        self._write_stats()
        output = self._call_with_logs()
        assert any("10 contests parsed but none upserted" in line for line in output)
