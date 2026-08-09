from unittest.mock import Mock, call, patch

from django.test import SimpleTestCase

from ranking.management.modules import dl_gsu


class DlGsuAuthenticationTest(SimpleTestCase):
    def test_authenticated_page_replaces_expired_cached_response(self):
        target_url = "https://dl.gsu.by/tasks/taskchoi.jsp?c.id=19"
        login_form = {
            "method": "post",
            "url": "login.jsp",
            "post": {"logon": "login"},
        }
        redirect_form = {
            "method": "post",
            "url": "/logon.asp",
            "post": {"logon": "submit"},
        }
        requester = Mock()
        requester.current_url = "https://dl.gsu.by/expired.asp"
        requester.get.side_effect = ["expired", "redirect", "desk", "standings"]
        requester.form.side_effect = [login_form, redirect_form, None]

        with (
            patch.object(dl_gsu, "req", requester),
            patch.object(dl_gsu.conf, "DLGSU_ID", "test-id"),
            patch.object(dl_gsu.conf, "DLGSU_PASSWORD", "test-password"),
        ):
            assert dl_gsu.Statistic._get(target_url) == "standings"

        assert requester.get.call_args_list == [
            call(target_url),
            call(
                "https://dl.gsu.by/login.jsp",
                post={"logon": "login", "id": "test-id", "password": "test-password"},
                content_type=None,
                caching=False,
            ),
            call(
                "https://dl.gsu.by/logon.asp",
                post={"logon": "submit"},
                content_type=None,
                caching=False,
            ),
            call(target_url, refresh_cache=True),
        ]
