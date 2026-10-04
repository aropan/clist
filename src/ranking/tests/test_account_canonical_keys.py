import json
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from ranking.management.modules import (
    algoleague,
    atcoder,
    codechef,
    codeforces,
    codingame,
    csacademy,
    dmoj,
    e_olymp,
    kaggle,
    leetcode,
    lightoj,
    luogu,
    my_newtonschool,
    robocontest,
    samcoding_uz,
    tlx_toki,
    toph,
    uoj,
)
from ranking.models import Account


class AccountCanonicalKeysTest(SimpleTestCase):
    def assert_canonical_profile(self, result, user, canonical_key):
        assert result["info"]
        assert result["canonical_key"] == canonical_key
        if user == canonical_key:
            assert "rename" not in result
        else:
            assert result["rename"] == canonical_key

    def test_atcoder_uses_matching_username_link_in_either_attribute_order(self):
        resource = SimpleNamespace(profile_url="https://atcoder.jp/users/{account}")
        for link in (
            '<a href="/users/Canonical" class="username"><span>Canonical</span></a>',
            "<a class='bold username highlight' href='/users/Canonical'>Canonical</a>",
        ):
            for user in ("canonical", "Canonical"):
                page = '<a href="/users/other" class="username">other</a>' + link
                with (
                    self.subTest(link=link, user=user),
                    mock.patch.object(atcoder.Statistic, "_get", return_value=page),
                    mock.patch.object(atcoder, "rate_limiter", side_effect=lambda func: func),
                ):
                    (result,) = atcoder.Statistic.get_users_infos([user], resource, [])

                self.assert_canonical_profile(result, user, "Canonical")

    def test_atcoder_does_not_confirm_unrelated_or_missing_username_links(self):
        resource = SimpleNamespace(profile_url="https://atcoder.jp/users/{account}")
        rating = '<tr><th class="no-break">Rating</th><td>1500</td></tr>'
        for link in (
            "",
            '<a href="/users/other" class="username">other</a>',
            '<a href="/users/canonical" class="not-username">canonical</a>',
        ):
            with (
                self.subTest(link=link),
                mock.patch.object(atcoder.Statistic, "_get", return_value=rating + link),
                mock.patch.object(atcoder, "rate_limiter", side_effect=lambda func: func),
            ):
                (result,) = atcoder.Statistic.get_users_infos(["canonical"], resource, [])

            assert result["info"]["rating"] == 1500
            assert "canonical_key" not in result
            assert "rename" not in result

    def test_codechef_uses_profile_current_user_instead_of_requested_url(self):
        for user in ("canonical", "Canonical"):
            data = {"username": "logged-in-user", "currentUser": "Canonical", "date_versus_rating": {"all": []}}
            page = f"jQuery.extend(Drupal.settings,{json.dumps(data)});"
            with (
                self.subTest(user=user),
                mock.patch.object(codechef.REQ, "with_proxy", return_value=nullcontext(None)),
                mock.patch.object(
                    codechef.Statistic,
                    "fetch_profle_page",
                    return_value=(page, f"https://www.codechef.com/users/{user}"),
                ),
            ):
                (result,) = codechef.Statistic.get_users_infos([user])

            self.assert_canonical_profile(result, user, "Canonical")

    def test_codechef_does_not_confirm_missing_or_unrelated_current_user(self):
        for current_user in (None, "other", 123):
            data = {"currentUser": current_user, "date_versus_rating": {"all": []}}
            page = (
                f"jQuery.extend(Drupal.settings,{json.dumps(data)});\n"
                "<li><label>Country:</label><span>Belarus</span></li>"
            )
            with (
                self.subTest(current_user=current_user),
                mock.patch.object(codechef.REQ, "with_proxy", return_value=nullcontext(None)),
                mock.patch.object(
                    codechef.Statistic,
                    "fetch_profle_page",
                    return_value=(page, "https://www.codechef.com/users/canonical"),
                ),
            ):
                (result,) = codechef.Statistic.get_users_infos(["canonical"])

            assert result["info"]
            assert "canonical_key" not in result
            assert "rename" not in result

    def test_api_profiles_restore_canonical_usernames(self):
        responses = (
            (dmoj, json.dumps({"data": {"object": {"username": "Canonical"}}})),
            (csacademy, json.dumps({"state": {"publicuser": [{"username": "other"}, {"username": "Canonical"}]}})),
            (my_newtonschool, json.dumps({"username": "Canonical"})),
            (algoleague, {"profile": {"userName": "Canonical", "name": "Real Name"}}),
            (samcoding_uz, {"username": "Canonical", "first_name": "Real Name"}),
        )
        resource = SimpleNamespace(url="https://example.com/")
        for module, response in responses:
            for user in ("canonical", "Canonical"):
                with (
                    self.subTest(module=module.__name__, user=user),
                    mock.patch.object(
                        module.REQ, "get", side_effect=lambda *args, response=response, **kwargs: deepcopy(response)
                    ),
                ):
                    (result,) = module.Statistic.get_users_infos([user], resource, [Account(key=user)])

                self.assert_canonical_profile(result, user, "Canonical")

    def test_api_profiles_without_identity_cannot_confirm_discovery(self):
        for module, response in (
            (dmoj, json.dumps({"data": {"object": {"name": "Real Name"}}})),
            (my_newtonschool, json.dumps({"name": "Real Name"})),
            (algoleague, {"profile": {"name": "Real Name"}}),
        ):
            with (
                self.subTest(module=module.__name__),
                mock.patch.object(module.REQ, "get", return_value=response),
            ):
                (result,) = module.Statistic.get_users_infos(
                    ["canonical"], SimpleNamespace(url="https://example.com/"), [Account(key="canonical")]
                )

            assert result["info"]
            assert "canonical_key" not in result
            assert "rename" not in result

    def test_robocontest_uses_profile_username(self):
        resource = SimpleNamespace(profile_url="https://robocontest.uz/profile/{account}")
        page = {"props": {"profile": {"username": "Canonical", "name": "Real Name"}}}
        for user in ("canonical", "Canonical"):
            with self.subTest(user=user), mock.patch.object(robocontest, "get_page_data", return_value=page):
                (result,) = robocontest.Statistic.get_users_infos([user], resource, [])

            self.assert_canonical_profile(result, user, "Canonical")

    def test_csacademy_prefers_exact_match_and_rejects_ambiguous_casing(self):
        response = json.dumps({"state": {"publicuser": [{"username": "Canonical"}, {"username": "canonical"}]}})
        with mock.patch.object(csacademy.REQ, "get", return_value=response):
            (result,) = csacademy.Statistic.get_users_infos(["canonical"], None, [])
            (ambiguous,) = csacademy.Statistic.get_users_infos(["CANONICAL"], None, [])

        self.assert_canonical_profile(result, "canonical", "canonical")
        assert ambiguous["skip"]
        assert "canonical_key" not in ambiguous

    def test_tlx_uses_api_username(self):
        for user in ("canonical", "Canonical"):

            def get(url, user=user, **kwargs):
                if url == tlx_toki.Statistic.API_USER_SEARCH_:
                    return json.dumps({user: "user-jid"})
                if url.endswith("/basic"):
                    return json.dumps({"username": "Canonical"})
                return json.dumps({"data": [], "contestsMap": {}})

            with self.subTest(user=user), mock.patch.object(tlx_toki.REQ, "get", side_effect=get):
                (result,) = tlx_toki.Statistic.get_users_infos([user], None, [])

            self.assert_canonical_profile(result, user, "Canonical")

    def test_kaggle_uses_api_username(self):
        for user in ("canonical", "Canonical"):
            req = mock.Mock()
            req.get.return_value = {"userProfile": {"userName": "Canonical", "displayName": "Real Name"}}
            with self.subTest(user=user), mock.patch.object(kaggle.REQ, "with_proxy", return_value=nullcontext(req)):
                (result,) = kaggle.Statistic.get_users_infos([user], None, [])

            self.assert_canonical_profile(result, user, "Canonical")

    def test_codeforces_confirms_both_unchanged_and_renamed_keys(self):
        for user in ("canonical", "Canonical"):
            with (
                self.subTest(user=user),
                mock.patch.object(
                    codeforces, "api_query", return_value={"status": "OK", "result": [{"handle": "Canonical"}]}
                ),
                mock.patch.object(codeforces.os, "environ", {}),
            ):
                (result,) = codeforces.Statistic.get_users_infos([user])

            self.assert_canonical_profile(result, user, "Canonical")

    def test_luogu_uses_numeric_uid_instead_of_display_username(self):
        resource = SimpleNamespace(url="https://www.luogu.com.cn/")
        for user in ("42", "00042"):
            data = {"data": {"user": {"uid": 42, "name": "Display Name"}, "elo": []}}
            page = f'<script id="lentille-context">{json.dumps(data)}</script>'
            with self.subTest(user=user), mock.patch.object(luogu.Statistic, "_get", return_value=page):
                (result,) = luogu.Statistic.get_users_infos([user], resource, [])

            self.assert_canonical_profile(result, user, "42")

    def test_luogu_missing_uid_does_not_confirm_requested_key(self):
        page = '<script id="lentille-context">{"data":{"user":{"name":"Display Name"}}}</script>'
        with mock.patch.object(luogu.Statistic, "_get", return_value=page):
            (result,) = luogu.Statistic.get_users_infos(["42"], SimpleNamespace(url="https://www.luogu.com.cn/"), [])

        assert "canonical_key" not in result
        assert "rename" not in result

    def test_eolymp_keeps_opaque_member_id_separate_from_profile_nickname(self):
        member_id = "a" * 26
        account = Account(key=member_id)
        profile = {
            "data": {
                "member": {
                    "id": member_id,
                    "account": {"nickname": "Canonical", "name": None, "country": None},
                    "picture": None,
                    "stats": {},
                }
            }
        }
        history = {"data": {"performance": {"nodes": [], "pageInfo": {"hasNextPage": False}}}}
        with mock.patch.object(e_olymp.REQ, "get", side_effect=[profile, history]):
            (result,) = e_olymp.Statistic.get_users_infos([member_id], None, [account])

        self.assert_canonical_profile(result, member_id, member_id)
        assert result["info"]["profile_url"] == {"account": "Canonical"}

    def test_codingame_uses_numeric_user_id_instead_of_pseudo(self):
        account = Account(key="42", info={"profile_url": {"public_handle": "public-handle"}})
        resource = SimpleNamespace(profile_url="https://www.codingame.com/profile/{public_handle}")
        points = {"codingamer": {"userId": 42, "pseudo": "Display Name"}, "codingamePointsRankingDto": {}}
        with mock.patch.object(codingame.REQ, "get", side_effect=[json.dumps(points), "{}"]):
            (result,) = codingame.Statistic.get_users_infos([account.key], resource, [account])

        self.assert_canonical_profile(result, account.key, "42")

    def test_lightoj_uses_user_or_team_id_instead_of_handle(self):
        resource = SimpleNamespace(profile_url="https://lightoj.com/{kind}/{slug}")
        for kind, key in (("user", "42"), ("team", "team-42")):
            account = Account(key=key, info={"profile_url": {"kind": kind, "slug": "Canonical"}})
            data = {"data": [{kind: {f"{kind}Id": 42, f"{kind}NameStr": "Real Name"}}]}
            page = f"function() {{return {json.dumps(data)}}}());"
            with self.subTest(kind=kind), mock.patch.object(lightoj.REQ, "get", return_value=page):
                (result,) = lightoj.Statistic.get_users_infos([key], resource, [account])

            self.assert_canonical_profile(result, key, key)

    def test_uoj_uses_profile_heading_instead_of_requested_key(self):
        resource = SimpleNamespace(profile_url="https://uoj.ac/user/profile/{account}")
        page = '<h2><span class="uoj-honor" data-rating="1500">Canonical</span></h2><script>rating_data=[[]];</script>'
        for user in ("canonical", "Canonical"):
            with self.subTest(user=user), mock.patch.object(uoj, "req_get", return_value=page):
                (result,) = uoj.Statistic.get_users_infos([user], resource, [Account(key=user)])

            self.assert_canonical_profile(result, user, "Canonical")

    def test_toph_uses_canonical_profile_link_instead_of_requested_url(self):
        for link in (
            "<link rel=canonical href=https://toph.co/u/dip_BRUR/ratings>",
            '<link href="https://toph.co/u/dip_BRUR/ratings" rel="canonical">',
            "<link rel='canonical' href='https://toph.co/u/dip_BRUR/ratings'>",
        ):
            page = (
                link
                + '<div class="username">dip_BRUR</div>'
                + "<table><thead><tr><th>Contest</th><th>Rating</th></tr></thead><tbody></tbody></table>"
            )
            for user in ("dip_brur", "dip_BRUR"):
                with self.subTest(link=link, user=user), mock.patch.object(toph.REQ, "get", return_value=page):
                    (result,) = toph.Statistic.get_users_infos([user], None, [Account(key=user)])

                self.assert_canonical_profile(result, user, "dip_BRUR")

    def test_toph_missing_or_unrelated_canonical_link_does_not_confirm_discovery(self):
        for link in (
            "",
            '<link rel="canonical" href="https://toph.co/u/other/ratings">',
            "<link rel=canonical href=https://toph.co/u/other/ratings>",
        ):
            page = (
                link
                + '<div class="username">Canonical</div>'
                + "<table><thead><tr><th>Contest</th><th>Rating</th></tr></thead><tbody></tbody></table>"
            )
            with self.subTest(link=link), mock.patch.object(toph.REQ, "get", return_value=page):
                (result,) = toph.Statistic.get_users_infos(["canonical"], None, [Account(key="canonical")])

            assert result["info"]
            assert "canonical_key" not in result
            assert "rename" not in result

    def test_uoj_unrelated_profile_heading_does_not_confirm_discovery(self):
        page = '<h2><span class="uoj-honor">other</span></h2><script>rating_data=[[]];</script>'
        with mock.patch.object(uoj, "req_get", return_value=page):
            (result,) = uoj.Statistic.get_users_infos(
                ["canonical"],
                SimpleNamespace(profile_url="https://uoj.ac/user/profile/{account}"),
                [Account(key="canonical")],
            )

        assert "canonical_key" not in result
        assert "rename" not in result

    def test_leetcode_rejects_unknown_domain_before_profile_requests(self):
        account = Account(key="canonical@.example")
        with (
            mock.patch.object(leetcode.REQ, "with_proxy", return_value=nullcontext(mock.Mock())),
            mock.patch.object(leetcode.os.path, "exists", return_value=False),
            mock.patch.object(leetcode.Statistic, "_get") as request_get,
            mock.patch.object(leetcode.tqdm, "tqdm", return_value=mock.MagicMock()),
        ):
            (result,) = leetcode.Statistic.get_users_infos([account.key], None, [account])

        assert result == {"skip": True}
        request_get.assert_not_called()

    def test_leetcode_key_and_profile_handle_follow_standings_normalization(self):
        for domain in (".com", ".COM", ".cn", ".CN"):
            for handle in ("canonical", "Canonical"):
                account = Account(key=f"{handle}@{domain}")
                if domain.lower() == ".com":
                    profile = {"data": {"matchedUser": {"username": "Canonical", "profile": {"realName": "Real Name"}}}}
                else:
                    profile = {
                        "data": {
                            "userProfilePublicProfile": {"profile": {"userSlug": "Canonical", "realName": "Real Name"}}
                        }
                    }
                ranking = {"data": {"userContestRanking": None, "userContestRankingHistory": []}}
                with (
                    self.subTest(domain=domain, handle=handle),
                    mock.patch.object(leetcode.REQ, "with_proxy", return_value=nullcontext(mock.Mock())),
                    mock.patch.object(leetcode.os.path, "exists", return_value=False),
                    mock.patch.object(
                        leetcode.Statistic, "_get", side_effect=[json.dumps(profile), json.dumps(ranking)]
                    ),
                    mock.patch.object(leetcode.tqdm, "tqdm", return_value=mock.MagicMock()),
                ):
                    (result,) = leetcode.Statistic.get_users_infos([account.key], None, [account])

                self.assert_canonical_profile(result, account.key, f"canonical@{domain.lower()}")
                assert result["info"]["profile_url"] == {"_domain": domain.lower(), "_handle": "canonical"}
