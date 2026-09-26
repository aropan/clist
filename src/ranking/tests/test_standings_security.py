from html.parser import HTMLParser
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.test.client import RequestFactory

from clist.templatetags.extras import (
    coder_color_circle,
    format_score,
    format_status,
    icon_to,
    medal_percentage,
    profile_url,
    safe_href,
    standings_statistic_problem,
    standings_statistic_problem_attributes,
    submission_info_field,
)


class ElementParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def parse_elements(markup):
    parser = ElementParser()
    parser.feed(str(markup))
    return parser.elements


class StandingsHtmlSecurityTest(SimpleTestCase):
    def test_versus_game_links_reject_active_urls(self):
        context = {
            "statistic": SimpleNamespace(pk=1),
            "versus_data": {"games": {"fields": ["url"]}},
            "versus_data_row": {
                "games": [
                    {"players": [{"name": "Alice"}], "url": "javascript:alert(1)"},
                    {"url": "data:text/html,<script>alert(1)</script>"},
                ],
            },
        }

        elements = parse_elements(render_to_string("standings_versus_games.html", context))
        links = [attrs for tag, attrs in elements if tag == "a"]

        assert len(links) == 2
        assert all(attrs["href"] == "" for attrs in links)

    def test_problem_attributes_escape_parser_values(self):
        attack = 'value" onmouseover="alert(1)'
        context = {
            "contest": SimpleNamespace(is_stage=lambda: False),
            "statistic": SimpleNamespace(my_stat=False, virtual_start=None),
            "problem": {"short": attack, "full_score": attack},
            "stat": {"_class": attack, "result": attack, "time": attack, "penalty": attack},
        }

        attributes = standings_statistic_problem_attributes(context)
        elements = parse_elements(f"<td {attributes}></td>")

        assert len(elements) == 1
        assert "onmouseover" not in elements[0][1]
        assert elements[0][1]["data-problem-key"] == attack
        assert elements[0][1]["data-result"] == attack

    def test_problem_content_escapes_untrusted_markup(self):
        attack = '<img src=x onerror="alert(1)">'
        context = {
            "request": RequestFactory().get("/"),
            "statistic": SimpleNamespace(pk=1, my_stat=False, virtual_start=None),
            "contest": SimpleNamespace(is_over=lambda: False, is_stage=lambda: False),
            "key": "A",
            "stat": {
                "result": attack,
                "result_name": attack,
                "result_name_class": 'x" onmouseover="alert(1)',
                "icon": attack,
            },
            "with_result_name": True,
        }

        content = standings_statistic_problem(context)
        elements = parse_elements(content)

        assert not any(tag == "img" or "onerror" in attrs or "onmouseover" in attrs for tag, attrs in elements)
        assert "&lt;img" in str(content)

    def test_links_and_html_tags_reject_active_markup(self):
        for url in ("javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "java\nscript:alert(1)"):
            assert safe_href(url) == ""
        assert safe_href("https://example.com/path") == "https://example.com/path"
        assert safe_href("/contest/1") == "/contest/1"
        assert safe_href("http://[invalid") == ""

        account = SimpleNamespace(info={}, dict_with_info=lambda: {"key": 'a" onmouseover="alert(1)'})
        resource = SimpleNamespace(profile_url="https://example.com/{key}")
        link = parse_elements(profile_url(account, resource=resource))
        assert "onmouseover" not in link[0][1]

        icon = parse_elements(icon_to("to_list", title='x" onmouseover="alert(1)'))
        assert "onmouseover" not in icon[0][1]

        medal = parse_elements(medal_percentage("gold", 0.5, info='x" onmouseover="alert(1)'))
        assert not any("onmouseover" in attrs for _, attrs in medal)

        resource = SimpleNamespace(
            info={},
            get_rating_color=lambda values, value_name=None: ({"hex_rgb": 'red" onload="alert(1)'}, 100),
        )
        circle = parse_elements(coder_color_circle(resource, {"rating": 100}))
        assert not any("onload" in attrs for _, attrs in circle)

        submission = parse_elements(
            submission_info_field({"_submission_infos": [{"ip": 'x" onmouseover="alert(1)'}]}, "ip")
        )
        assert not any("onmouseover" in attrs for _, attrs in submission)

        assert "<img" not in str(format_score('<img src=x onerror="alert(1)">'))
        assert format_status("ok", 'img src=x onerror="alert(1)"', True) == "ok"
