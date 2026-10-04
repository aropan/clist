import json
import os
import tempfile
from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml
from bs4 import BeautifulSoup
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse
from django.utils import timezone
from django_countries.fields import Country
from geoip2.errors import AddressNotFoundError
from oauth2_provider.checks import validate_bcp_configuration
from oauth2_provider.models import Application

from clist.api.paginator import EstimatedCountPaginator
from clist.models import Contest, Problem, Resource
from clist.oauth_application import check_oauth_application_redirect_uris
from clist.templatetags.extras import (
    allow_custom_countries,
    format_score,
    get_country_code,
    get_country_from,
    get_custom_country,
    get_geo_country_code,
    get_new_rating_value,
)
from clist.views import get_view_contests
from pyclist.indexes import GinIndexTrgrmOps
from pyclist.sitemaps import CodersSitemap, ResourcesSitemap, StandingsSitemap, StaticViewSitemap, sitemaps
from ranking.models import Account, CountryAccount
from true_coders.models import Coder


class CountryTemplateTagsTest(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/")
        self.request.user = AnonymousUser()

    def test_missing_country_is_supported(self):
        assert allow_custom_countries(self.request, None) is False
        assert get_custom_country(self.request, None, {"BY": "BPR"}) is None
        assert get_country_from({"request": self.request}, None, {"BY": "BPR"}) is None
        assert get_country_code(None) is None
        assert get_country_code("") == ""

    def test_country_objects_and_alternative_codes_are_normalized(self):
        for value in (Country("BY"), "BY", "by", "BLR", "112", "Belarus"):
            with self.subTest(value=value):
                assert get_country_code(value) == "BY"

    def test_unknown_and_empty_country_objects_are_supported(self):
        for value in (Country("XX"), Country("ZZ"), Country(None), Country(""), "unknown country"):
            with self.subTest(value=value):
                assert get_country_code(value) == ""

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


class StandingsFormattingTest(SimpleTestCase):
    def test_format_score_reuses_request_cache(self):
        cache = {}
        with mock.patch("clist.templatetags.extras.scoreformat", return_value="formatted") as scoreformat:
            assert format_score(10, cache) == "formatted"
            assert format_score(10, cache) == "formatted"

        scoreformat.assert_called_once_with(10)


class ResourceRatingColorTest(SimpleTestCase):
    def test_rating_without_coloring_field_boundaries_has_no_color(self):
        resource = Resource(
            info={"ratings": {"chartjs": {"coloring_field": "rank"}}},
            ratings=[{"low": 1, "high": 21, "min_rating": None}],
        )

        assert resource.get_rating_color(792, value_name="rating") == (None, None)


class ResourceRatingValueTest(SimpleTestCase):
    def test_missing_resource_returns_none(self):
        assert get_new_rating_value(None, {"new_rating": 2435}) is None

    def test_statistic_rating_does_not_require_resource_color_scale(self):
        resource = Resource(ratings=[])

        assert get_new_rating_value(resource, {"new_rating": 2435, "rating_change": 20}) == 2435

    def test_missing_current_rating_returns_none(self):
        resource = Resource(ratings=[])

        assert get_new_rating_value(resource, {"old_rating": 2415}) is None


class ContestStandingsPerPageTest(SimpleTestCase):
    def test_small_contest_uses_full_table_page_size(self):
        contest = Contest(info={}, n_statistics=163)

        assert contest.standings_per_page == 163

    def test_small_contest_uses_full_table_despite_explicit_page_size(self):
        contest = Contest(info={"standings": {"per_page": 75}}, n_statistics=499)

        assert contest.standings_per_page == 499

    def test_none_page_size_still_requests_full_table(self):
        contest = Contest(info={"standings": {"per_page": None}}, n_statistics=499)

        assert contest.standings_per_page == 100500

    def test_large_contest_keeps_configured_page_size(self):
        contest = Contest(info={}, n_statistics=501)

        assert contest.standings_per_page == 50


class ProblemSearchIndexTest(SimpleTestCase):
    def test_key_has_trigram_gin_index(self):
        indexes = [index for index in Problem._meta.indexes if index.fields == ["key"]]

        assert len(indexes) == 1
        assert isinstance(indexes[0], GinIndexTrgrmOps)


# the dev container runs with DEBUG=True, which appends debug-only middleware that breaks page tests
DEBUG_ONLY_MIDDLEWARE = {
    # redirects anonymous requests to the login page, so rendered pages are never reached
    "pyclist.middleware.DebugPermissionOnlyMiddleware",
    # SILKY_PYTHON_PROFILER makes silk EXPLAIN every query, and those statements leak into the query
    # counts captured by unrelated tests
    "silk.middleware.SilkyMiddleware",
}
MIDDLEWARE_WITHOUT_DEBUG_TOOLING = [
    middleware for middleware in settings.MIDDLEWARE if middleware not in DEBUG_ONLY_MIDDLEWARE
]

# cphof imports name virtual coders with a U+2228 prefix and a numeric id, the only non-ascii usernames
VIRTUAL_CODER_USERNAME = "\u222842"
VIRTUAL_CODER_LOCATION = "/coder/%E2%88%A842/"


class SitemapTest(TestCase):
    @classmethod
    def create_contest(cls, key, title, end_time, created, **kwargs):
        contest = Contest.objects.create(
            resource=cls.resource,
            title=title,
            start_time=end_time - timedelta(hours=1),
            end_time=end_time,
            duration_in_secs=3600,
            url=f"https://sitemap.example/contest/{key}",
            key=key,
            host=cls.resource.host,
            n_statistics=1,
            **kwargs,
        )
        # created is auto_now_add, so it can only be moved with an explicit update
        Contest.objects.filter(pk=contest.pk).update(created=created)
        return Contest.objects.get(pk=contest.pk)

    @classmethod
    def create_coder(cls, username, n_contests, created, **kwargs):
        coder = Coder.objects.create(username=username, n_contests=n_contests, **kwargs)
        Coder.objects.filter(pk=coder.pk).update(created=created)
        return Coder.objects.get(pk=coder.pk)

    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.now = now
        cls.update_icon_patcher = mock.patch.object(Resource, "update_icon")
        cls.update_icon_patcher.start()
        cls.addClassCleanup(cls.update_icon_patcher.stop)
        cls.resource = Resource.objects.create(
            host="sitemap.example",
            enable=True,
            url="https://sitemap.example/",
            n_contests=3,
        )
        cls.empty_resource = Resource.objects.create(
            host="empty.example",
            enable=True,
            url="https://empty.example/",
        )

        long_ago = now - timedelta(days=30)
        # the freshest parsed_time belongs to a contest that is not first in the queryset order
        cls.recently_parsed = cls.create_contest(
            "sitemap-0",
            "Sitemap contest 0",
            now - timedelta(days=2),
            long_ago,
            parsed_time=now - timedelta(hours=1),
        )
        cls.without_parsed_time = cls.create_contest(
            "sitemap-1",
            "Sitemap contest 1",
            now - timedelta(days=3),
            long_ago,
        )
        cls.create_contest("sitemap-2", "Sitemap contest 2", now - timedelta(days=4), long_ago)
        # ran long ago but the row is new, so it must still reach the sitemap
        cls.backfilled = cls.create_contest(
            "sitemap-backfilled",
            "Sitemap backfilled contest",
            now - timedelta(days=400),
            now,
            parsed_time=now - timedelta(days=10),
        )
        cls.invisible = cls.create_contest(
            "sitemap-invisible",
            "Sitemap invisible contest",
            now - timedelta(days=2),
            long_ago,
            invisible=True,
        )
        cls.unfinished = cls.create_contest(
            "sitemap-unfinished",
            "Sitemap unfinished contest",
            now + timedelta(days=1),
            long_ago,
        )

        cls.top_coder = cls.create_coder("top-coder", 500, long_ago)
        cls.virtual_coder = cls.create_coder(
            VIRTUAL_CODER_USERNAME,
            300,
            long_ago,
            is_virtual=True,
            settings={"display_name": "Virtual Person"},
        )
        cls.new_coder = cls.create_coder("new-coder", 10, now)
        cls.thin_coder = cls.create_coder("thin-coder", 1, now)

        cls.account = Account.objects.create(
            resource=cls.resource,
            key="winner",
            last_activity=now - timedelta(days=2),
        )
        cls.account.coders.add(cls.virtual_coder)

        # linking an account recomputes Coder.n_contests, so pin the fixture values afterwards
        for coder, n_contests in (
            (cls.top_coder, 500),
            (cls.virtual_coder, 300),
            (cls.new_coder, 10),
            (cls.thin_coder, 1),
        ):
            Coder.objects.filter(pk=coder.pk).update(n_contests=n_contests)
            coder.n_contests = n_contests

    def test_root_is_sitemap_index_with_section_urls(self):
        assert resolve("/sitemap.xml").url_name == "django.contrib.sitemaps.views.index"
        assert reverse("django.contrib.sitemaps.views.sitemap", kwargs={"section": "coders"}) == "/sitemap-coders.xml"
        assert set(sitemaps) == {"static", "standings", "coders", "resources"}
        assert all(not hasattr(sitemap_class, "priority") for sitemap_class in sitemaps.values())
        assert all(not hasattr(sitemap_class, "changefreq") for sitemap_class in sitemaps.values())

    def test_all_sections_use_limit_as_total_size(self):
        for sitemap_class in sitemaps.values():
            with self.subTest(section=sitemap_class.__name__):
                sitemap = sitemap_class()

                assert sitemap.limit == 1000
                assert sitemap.paginator.count <= sitemap.limit
                assert sitemap.paginator.num_pages == 1

    def test_static_items_are_expected_urls(self):
        assert StaticViewSitemap().items() == [
            "clist:main",
            "clist:resources",
            "clist:resources_account_ratings",
            "clist:resources_country_ratings",
            "ranking:standings_list",
            "clist:problems",
            "coder:coders",
            "clist:links",
            "clist:api:latest:index",
        ]

    def test_standings_items_use_one_query_and_one_page(self):
        with CaptureQueriesContext(connection) as queries:
            sitemap = StandingsSitemap()
            contests = list(sitemap.items())

        assert len(contests) == 4
        assert len(queries) == 1
        assert sitemap.items().query.high_mark == sitemap.limit == 1000
        assert sitemap.paginator.num_pages == 1

    def test_standings_excludes_invisible_and_unfinished_contests(self):
        ids = {contest.id for contest in StandingsSitemap().items()}

        assert self.invisible.pk not in ids
        assert self.unfinished.pk not in ids

    def test_standings_backfilled_contest_sorts_first(self):
        contests = list(StandingsSitemap().items())

        # its end_time is the oldest of all, so only Greatest(end_time, created) can put it first
        assert contests[0].id == self.backfilled.pk
        assert self.backfilled.end_time == min(contest.end_time for contest in contests)

    def test_standings_lastmod_prefers_parsed_time_over_end_time(self):
        sitemap = StandingsSitemap()
        contests = {contest.id: contest for contest in sitemap.items()}

        assert sitemap.lastmod(contests[self.recently_parsed.pk]) == self.recently_parsed.parsed_time
        assert sitemap.lastmod(contests[self.without_parsed_time.pk]) == self.without_parsed_time.end_time

    def test_get_latest_lastmod_returns_maximum_not_first_item(self):
        sitemap = StandingsSitemap()
        first = next(iter(sitemap.items()))

        assert sitemap.lastmod(first) != self.recently_parsed.parsed_time
        assert sitemap.get_latest_lastmod() == self.recently_parsed.parsed_time

    def test_coders_include_virtual_with_encoded_location(self):
        sitemap = CodersSitemap()
        usernames = {coder.username for coder in sitemap.items()}
        virtual = next(coder for coder in sitemap.items() if coder.username == self.virtual_coder.username)

        assert self.virtual_coder.username in usernames
        assert sitemap.location(virtual) == VIRTUAL_CODER_LOCATION

    def test_coders_lastmod_uses_account_last_activity(self):
        sitemap = CodersSitemap()
        virtual = next(coder for coder in sitemap.items() if coder.username == self.virtual_coder.username)

        assert self.virtual_coder.last_activity is None
        assert sitemap.lastmod(virtual) == self.account.last_activity

    def test_coders_recency_half_adds_new_coder_and_skips_thin_one(self):
        sitemap = CodersSitemap()
        sitemap.value_limit = 1
        items = sitemap.items()
        usernames = [coder.username for coder in items]

        assert usernames[0] == self.top_coder.username
        assert self.new_coder.username in usernames
        assert self.thin_coder.username not in usernames
        assert len(usernames) == len({coder.id for coder in items})

    def test_resources_exclude_resource_without_contests(self):
        hosts = {resource.host for resource in ResourcesSitemap().items()}

        assert self.resource.host in hosts
        assert self.empty_resource.host not in hosts

    @override_settings(MIDDLEWARE=MIDDLEWARE_WITHOUT_DEBUG_TOOLING)
    def test_resource_canonical_matches_sitemap_location(self):
        resource = next(iter(ResourcesSitemap().items()))
        expected = f'<link rel="canonical" href="http://testserver{ResourcesSitemap().location(resource)}">'

        for url in (f"/resource/{self.resource.pk}/", f"/resource/{self.resource.host}/"):
            with self.subTest(url=url):
                response = self.client.get(url)

                assert response.status_code == 200
                assert expected in response.content.decode()

    @override_settings(MIDDLEWARE=MIDDLEWARE_WITHOUT_DEBUG_TOOLING)
    def test_coder_canonical_is_percent_encoded(self):
        location = CodersSitemap().location(self.virtual_coder)

        response = self.client.get(location)

        assert response.status_code == 200
        assert f'<link rel="canonical" href="http://testserver{location}">' in response.content.decode()


@override_settings(MIDDLEWARE=MIDDLEWARE_WITHOUT_DEBUG_TOOLING)
class ResourceMedalDisplayTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        patcher = mock.patch.object(Resource, "update_icon")
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        cls.resource = Resource.objects.create(
            host="medal-display.example.com",
            url="https://medal-display.example.com/",
            enable=True,
            has_statistic_medal=True,
            has_country_medal=True,
        )
        Account.objects.bulk_create([
            Account(
                resource=cls.resource,
                key=f"medal-user-{index}",
                url=reverse("coder:account", args=[f"medal-user-{index}", cls.resource.host]),
                country="PL",
                n_win=3,
                n_gold=5,
                n_silver=7,
                n_bronze=11,
                n_medals=23,
            )
            for index in range(11)
        ])
        CountryAccount.objects.bulk_create([
            CountryAccount(
                resource=cls.resource,
                country=country,
                n_win=13,
                n_gold=17,
                n_silver=19,
                n_bronze=23,
                n_medals=59,
            )
            for country in ("PL", "DE", "FR", "ES", "IT", "GB", "US", "CA", "JP", "KR", "CN")
        ])

    def get_page(self, flag, **params):
        self.resource.medal_win_equals_gold = flag
        self.resource.save(update_fields=["medal_win_equals_gold"])
        response = self.client.get(
            reverse("clist:resource", args=[self.resource.host]),
            params,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest" if params else "",
        )
        assert response.status_code == 200
        return response

    def assert_medal_row(self, row, flag, country=False):
        expected = [13, 19, 23, 59] if country else [3, 7, 11, 23]
        if flag is False:
            expected.insert(1, 17 if country else 5)
        cells = row.find_all("td", recursive=False)[2:]
        assert [int(cell.get_text(strip=True)) for cell in cells] == expected
        if not country:
            filters = ["place:1", "medal:silver", "medal:bronze", "medal:"]
            if flag is False:
                filters.insert(1, "medal:gold")
            assert [parse_qs(urlsplit(cell.find("a")["href"]).query)["search"][0] for cell in cells] == filters

    def test_admin_form_accepts_all_three_states(self):
        request = RequestFactory().get("/admin/clist/resource/")
        request.user = mock.Mock(is_superuser=True)
        form_class = admin.site._registry[Resource].get_form(request)
        field = form_class.base_fields["medal_win_equals_gold"]
        for value, expected in (("unknown", None), ("true", True), ("false", False)):
            assert field.clean(value) is expected

    def test_resource_medal_tables_and_shortcut_follow_setting(self):
        for flag in (None, True, False):
            with self.subTest(flag=flag):
                response = self.get_page(flag)
                soup = BeautifulSoup(response.content, "html.parser")
                for title, country in (("Most medals", False), ("Countries most medals", True)):
                    header = next(element for element in soup.find_all("h4") if title in element.get_text())
                    table = header.find_next("table")
                    columns = table.find("tr").find_all("th")[2:]
                    assert len(columns) == (5 if flag is False else 4)
                    assert "fa-trophy" in str(columns[0])
                    assert ("gold-trophy" in str(columns[1])) is (flag is False)
                    row = next(row for row in table.find_all("tr") if len(row.find_all("td", recursive=False)) > 2)
                    self.assert_medal_row(row, flag, country=country)
                    if not country:
                        shortcut = parse_qs(urlsplit(header.find("a")["href"]).query)
                        fields = ["n_win", "n_silver", "n_bronze", "n_medals"]
                        if flag is False:
                            fields.insert(1, "n_gold")
                        assert shortcut["field"] == shortcut["sort_column"] == fields

                account = Account.objects.filter(resource=self.resource).first()
                assert account.n_gold == 5
                assert account.n_medals == 23
                self.resource.refresh_from_db()
                assert self.resource.medal_win_equals_gold is flag

    def test_medal_pagination_keeps_columns_and_filters(self):
        for flag in (None, True, False):
            for page, country in (("most_medals_page", False), ("country_most_medals_page", True)):
                with self.subTest(flag=flag, page=page):
                    response = self.get_page(flag, **{page: 2, "querystring_key": page})
                    assert response.context["page_template"] == (
                        "resource_country_most_medals.html" if country else "resource_most_medals_paging.html"
                    )
                    soup = BeautifulSoup(response.content, "html.parser")
                    rows = [row for row in soup.find_all("tr") if len(row.find_all("td", recursive=False)) > 2]
                    assert len(rows) == 1
                    self.assert_medal_row(rows[0], flag, country=country)

    def create_primary_medal_entries(self):
        account = Account.objects.filter(resource=self.resource).order_by("id").first()
        country = CountryAccount.objects.get(resource=self.resource, country="PL")
        user = User.objects.create_user(username="medal-display-user")
        coder = Coder.objects.create(user=user, country="PL")
        coder.account_set.add(account)
        self.client.force_login(user)
        return account, country

    def assert_primary_medal_positions(self, account, country):
        for flag in (None, True, False):
            for page in (None, "most_medals_page", "country_most_medals_page"):
                with self.subTest(flag=flag, page=page):
                    params = {page: 2, "querystring_key": page} if page else {}
                    response = self.get_page(flag, **params)
                    soup = BeautifulSoup(response.content, "html.parser")
                    for name, context_key, primary in (
                        ("most_medals", "most_medals", account),
                        ("country_most_medals", "country_medals", country),
                    ):
                        if page and page != f"{name}_page":
                            continue
                        ordered_ids = list(response.context[context_key].values_list("pk", flat=True))
                        position = ordered_ids.index(primary.pk) + 1
                        assert position == 11
                        rows = soup.find_all(
                            "tr", attrs={"data-delete-on-duplicate": f"delete-on-duplicate-{name}-{primary.pk}"}
                        )
                        pinned_rows = [row for row in rows if not row.has_attr("data-delete-on-duplicate-stop")]
                        assert len(pinned_rows) == 1
                        cells = pinned_rows[0].find_all("td", recursive=False)
                        assert int(cells[0].get_text(strip=True)) == position
                        assert len(cells) == (7 if flag is False else 6)

    def test_primary_medal_positions_include_hidden_gold(self):
        account, country = self.create_primary_medal_entries()
        Account.objects.filter(pk=account.pk).update(n_gold=4, n_silver=8)
        CountryAccount.objects.filter(pk=country.pk).update(n_gold=16, n_silver=20)

        self.assert_primary_medal_positions(account, country)

    def test_primary_medal_positions_follow_other_medals_order(self):
        account, country = self.create_primary_medal_entries()
        Account.objects.filter(resource=self.resource).update(n_other_medals=1)
        CountryAccount.objects.filter(resource=self.resource).update(n_other_medals=1)
        Account.objects.filter(pk=account.pk).update(n_other_medals=None)
        CountryAccount.objects.filter(pk=country.pk).update(n_other_medals=None)

        self.assert_primary_medal_positions(account, country)


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
