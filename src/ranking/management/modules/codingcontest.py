import math
import re
from collections import defaultdict
from urllib.parse import urljoin

from unidecode import unidecode

from clist.templatetags.extras import slug, trim_to
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse


class Statistic(BaseModule):
    @staticmethod
    def _key_part(value):
        value = re.sub(r"[^-a-z0-9_]+", "-", unidecode(value).lower())
        value = slug(value)
        value = trim_to(value, 100, raw_text=True)
        return value

    def _parse_entry(self, entry, page):
        context = f"contest {self.key}, page {page}"
        if not isinstance(entry, dict):
            raise ExceptionParseStandings(f"Invalid entry for {context}")
        for field, minimum in (("rank", 1), ("level", 0), ("timeMs", 0)):
            value = entry.get(field)
            if type(value) is not int or value < minimum:
                raise ExceptionParseStandings(f"Invalid {field} for {context}")
        for field in ("playerName", "venueName"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ExceptionParseStandings(f"Invalid {field} for {context}")
        if type(entry.get("isSolo")) is not bool:
            raise ExceptionParseStandings(f"Invalid isSolo for {context}")
        for field in ("teamName", "venueCity", "displayScore"):
            value = entry.get(field)
            if value is not None and not isinstance(value, str):
                raise ExceptionParseStandings(f"Invalid {field} for {context}")
        score = entry.get("score")
        if (
            "score" not in entry
            or (score is not None and type(score) not in (int, float))
            or (isinstance(score, float) and not math.isfinite(score))
        ):
            raise ExceptionParseStandings(f"Invalid score for {context}")

        parts = (
            entry["playerName"],
            "solo" if entry["isSolo"] else "team",
            entry["venueName"],
            entry.get("venueCity") or "",
        )
        member = f"{self.key}:" + ":".join(self._key_part(part) or "-" for part in parts)
        row = {
            "member": member,
            "name": entry["playerName"],
            "place": entry["rank"],
            "solving": score if score is not None else entry["level"],
            "level": entry["level"],
            "mode": "Solo" if entry["isSolo"] else "Team",
            "time": self.to_time(entry["timeMs"] / 1000, num=3),
            "time_ms": entry["timeMs"],
            "venue": entry["venueName"],
            "info": {"is_team": not entry["isSolo"], "_no_profile_url": True},
        }
        for field, output in (("venueCity", "city"), ("teamName", "team_name"), ("displayScore", "display_score")):
            if entry.get(field) is not None:
                row[output] = entry[field]
        return row

    def get_standings(self, users=None, statistics=None, **kwargs):
        if not str(self.key).isascii() or not str(self.key).isdigit():
            raise ExceptionParseStandings("Expected a numeric contest key")
        api_url = urljoin(self.resource.url, f"/api/hall-of-fame/contests/{self.key}/leaderboard")
        grouped_rows = defaultdict(list)
        totals = None
        page = 0
        while True:
            url = f"{api_url}?page={page}&size=100"
            try:
                data = REQ.get(url, return_json=True)
            except (FailOnGetResponse, ValueError) as error:
                raise ExceptionParseStandings(f"Failed to load {url}: {error}") from error
            if not isinstance(data, dict):
                raise ExceptionParseStandings(f"Invalid leaderboard response on {url}")
            content = data.get("content")
            if not isinstance(content, list):
                raise ExceptionParseStandings(f"Invalid leaderboard content on {url}")
            for field, minimum in (("page", 0), ("size", 1), ("totalPages", 0), ("totalElements", 0)):
                value = data.get(field)
                if type(value) is not int or value < minimum:
                    raise ExceptionParseStandings(f"Invalid {field} on {url}")
            if data["page"] != page:
                raise ExceptionParseStandings(f"Unexpected page on {url}: {data['page']}")

            current_totals = (data["totalPages"], data["totalElements"], data["size"])
            if totals is not None and current_totals != totals:
                raise ExceptionParseStandings(f"Inconsistent pagination on {url}")
            totals = current_totals
            total_pages, total_entries, size = totals
            if total_entries:
                expected_pages = (total_entries + size - 1) // size
                if total_pages != expected_pages:
                    raise ExceptionParseStandings(f"Incomplete pagination on {url}: expected {expected_pages} pages")
            elif total_pages not in (0, 1):
                raise ExceptionParseStandings(f"Incomplete pagination on {url}: invalid empty leaderboard")

            expected_entries = min(size, total_entries - page * size)
            if len(content) != expected_entries:
                raise ExceptionParseStandings(f"Incomplete pagination on {url}: expected {expected_entries} entries")
            for entry in content:
                row = self._parse_entry(entry, page)
                grouped_rows[row["member"]].append(row)
            page += 1
            if page >= total_pages:
                break

        result = {}
        for base_key, rows in grouped_rows.items():
            if len(rows) == 1:
                base_key = base_key.removesuffix(":-")
            rows.sort(key=lambda row: (row["name"], row["venue"], row.get("city") or ""))
            for index, row in enumerate(rows):
                member = f"{base_key}:{index}" if index else base_key
                row["member"] = member
                result[member] = row

        if len(result) != total_entries:
            raise ExceptionParseStandings(f"Incomplete leaderboard for contest {self.key}")
        if users is not None:
            selected = set(users)
            result = {member: row for member, row in result.items() if member in selected}
        return {
            "result": result,
            "fixed_fields": ["time"],
            "hidden_fields": ["time_ms", "display_score", "team_name", "venue", "city"],
        }
