import json
import os
import tempfile
from unittest import mock

import pytest
import yaml
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from geoip2.errors import AddressNotFoundError
from oauth2_provider.checks import validate_bcp_configuration
from oauth2_provider.models import Application

from clist.api.paginator import EstimatedCountPaginator
from clist.models import Resource
from clist.oauth_application import check_oauth_application_redirect_uris
from clist.templatetags.extras import (
    allow_custom_countries,
    get_country_from,
    get_custom_country,
    get_geo_country_code,
)
from clist.views import get_view_contests


class CountryTemplateTagsTest(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/")
        self.request.user = AnonymousUser()

    def test_missing_country_is_supported(self):
        assert allow_custom_countries(self.request, None) is False
        assert get_custom_country(self.request, None, {"BY": "BPR"}) is None
        assert get_country_from({"request": self.request}, None, {"BY": "BPR"}) is None

    def test_non_routable_ip_skips_geoip_lookup(self):
        geoip = mock.Mock()
        with (
            mock.patch("clist.templatetags.extras.get_client_ip", return_value=("127.0.0.1", False)),
            override_settings(GEOIP=geoip),
        ):
            assert get_geo_country_code(self.request) is None

        geoip.country_code.assert_not_called()

    def test_unknown_routable_ip_is_supported(self):
        geoip = mock.Mock()
        geoip.country_code.side_effect = AddressNotFoundError("address is absent")
        with (
            mock.patch("clist.templatetags.extras.get_client_ip", return_value=("192.0.2.1", True)),
            override_settings(GEOIP=geoip),
        ):
            assert get_geo_country_code(self.request) is None


class LoggingSettingsTest(SimpleTestCase):
    def test_django_errors_do_not_use_email_handler(self):
        assert "mail_admins" not in settings.LOGGING["handlers"]

        django_logger = settings.LOGGING["loggers"]["django"]
        assert django_logger["handlers"] == []
        assert django_logger["propagate"] is True

        root_handlers = settings.LOGGING["loggers"][""]["handlers"]
        assert "console_info" in root_handlers
        assert "production" in root_handlers


class OAuthSettingsTest(SimpleTestCase):
    def test_generic_redirect_scheme_warning_is_replaced_by_project_check(self):
        messages = validate_bcp_configuration(None)

        assert {message.id for message in messages} == {"oauth2_provider.W008"}
        assert "oauth2_provider.W008" in settings.SILENCED_SYSTEM_CHECKS


class OAuthApplicationRedirectURIValidationTest(TestCase):
    @staticmethod
    def make_application(redirect_uris, **kwargs):
        return Application(
            name="test application",
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris=redirect_uris,
            **kwargs,
        )

    def test_https_and_loopback_http_redirects_are_allowed(self):
        redirect_uris = (
            "https://example.com/callback",
            "http://localhost:8000/callback",
            "http://127.0.0.1:8000/callback",
            "http://[::1]:8000/callback",
        )
        for redirect_uri in redirect_uris:
            with self.subTest(redirect_uri=redirect_uri):
                self.make_application(redirect_uri).full_clean()

    def test_non_loopback_http_redirects_are_rejected(self):
        redirect_uris = (
            "http://example.com/callback",
            "http://localhost.example.com/callback",
            "http://127.0.0.1.example.com/callback",
        )
        for redirect_uri in redirect_uris:
            with self.subTest(redirect_uri=redirect_uri), pytest.raises(ValidationError) as error:
                self.make_application(redirect_uri).full_clean()

            assert "redirect_uris" in error.value.error_dict

    def test_non_loopback_post_logout_redirect_is_rejected(self):
        application = self.make_application(
            "https://example.com/callback",
            post_logout_redirect_uris="http://example.com/logout",
        )

        with pytest.raises(ValidationError) as error:
            application.full_clean()

        assert "post_logout_redirect_uris" in error.value.error_dict

    def test_pre_save_rejects_direct_model_save(self):
        with pytest.raises(ValidationError):
            self.make_application("http://example.com/callback").save()

        assert Application.objects.count() == 0

    def test_deploy_check_audits_existing_applications(self):
        application = self.make_application("https://example.com/callback")
        application.save()
        Application.objects.filter(pk=application.pk).update(redirect_uris="http://example.com/callback")

        messages = check_oauth_application_redirect_uris(None)

        assert {message.id for message in messages} == {"clist.E001"}


class GetViewContestsTestCase(TestCase):
    def test_invalid_past_days_uses_default(self):
        request = RequestFactory().get("/", {"past_days": "not-an-integer"})
        request.user = AnonymousUser()
        request.get_resources = lambda: []
        assert get_view_contests(request, coder=None) == []


class EstimatedCountPaginatorTest(TestCase):
    def test_postgres_estimated_count(self):
        paginator = EstimatedCountPaginator(
            {"total_count": "true"},
            Application.objects.all(),
        )

        estimated_count = paginator.get_estimated_count()

        assert isinstance(estimated_count, int)
        assert estimated_count >= 0


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

    def _call_with_logs(self, **extra):
        with self.assertLogs("clist.check_schedule_parsing", level="WARNING") as logs:
            call_command(
                "check_schedule_parsing",
                stats_file=self.stats_file,
                cache_file=self.cache_file,
                dryrun=True,
                **extra,
            )
        return logs.output

    def test_alert_on_stale_stats(self):
        self.stats_data["finished_at"] = int(self.now.timestamp()) - 24 * 60 * 60
        self._write_stats()
        output = self._call_with_logs()
        assert any("last schedule update finished" in line for line in output)

    def test_no_alert_on_recent_zero_parsed(self):
        # Produced within the grace period, so a zero run must not alert yet
        self._seed_cache({"last_nonzero_at": int(self.now.timestamp())})
        self.stats_data["resources"][0]["n_contests_parsed"] = 0
        self._write_stats()
        with pytest.raises(AssertionError):  # no warnings expected
            self._call_with_logs(zero_grace="1 hour")

    def test_alert_on_sustained_zero_parsed(self):
        # Produced within the window but nothing for longer than the grace period -> alert
        self._seed_cache({"last_nonzero_at": int(self.now.timestamp()) - 2 * 60 * 60})
        self.stats_data["resources"][0]["n_contests_parsed"] = 0
        self._write_stats()
        output = self._call_with_logs(zero_grace="1 hour")
        assert any("enabled.example.com: no contests parsed" in line for line in output)

    def test_no_alert_on_zero_parsed_long_inactive(self):
        # Last produced outside the window, so a zero run must not alert even past the grace period
        self._seed_cache({"last_nonzero_at": int(self.now.timestamp()) - 30 * 24 * 60 * 60})
        self.stats_data["resources"][0]["n_contests_parsed"] = 0
        self._write_stats()
        with pytest.raises(AssertionError):  # no warnings expected
            self._call_with_logs(zero_grace="1 hour")

    def test_alert_on_parsed_but_not_upserted(self):
        self._seed_cache({"last_upserted_at": int(self.now.timestamp())})
        self.stats_data["resources"][0]["n_contests_upserted"] = 0
        self._write_stats()
        output = self._call_with_logs()
        assert any("10 contests parsed but none upserted" in line for line in output)
