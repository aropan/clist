import json
import re
from copy import deepcopy
from datetime import timedelta
from urllib.parse import quote, urlencode, urljoin, urlsplit

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse
from utils.ratelimiter import RateLimiter


class Statistic(BaseModule):
    API_URL = "https://doj.kr/api/v1/"

    @staticmethod
    @RateLimiter(max_calls=1, period=0.6)
    def _get_api(path):
        return REQ.get(urljoin(Statistic.API_URL, path), return_json=True)

    @staticmethod
    def _get_pages(path, field, limit=200):
        cursor = None
        seen_cursors = set()
        while True:
            params = {"limit": limit}
            if cursor is not None:
                params["cursor"] = cursor
            data = Statistic._get_api(f"{path}?{urlencode(params)}")
            if not isinstance(data, dict) or not isinstance(data.get(field), list):
                raise ExceptionParseStandings(f"Invalid DOJ {field} response")
            yield from data[field]
            cursor = data.get("nextCursor")
            if cursor is None:
                break
            if cursor in seen_cursors:
                raise ExceptionParseStandings(f"Repeated DOJ {field} cursor")
            seen_cursors.add(cursor)

    @staticmethod
    def _get_page_data(page, fields):
        chunks = []
        for match in re.finditer(r"<script[^>]*>\s*self\.__next_f\.push\((\[.*?\])\)\s*</script>", page, re.S):
            data = json.loads(match[1])
            if len(data) > 1 and data[0] == 1 and isinstance(data[1], str):
                chunks.append(data[1])
        flight_data = "".join(chunks)
        decoder = json.JSONDecoder()
        for match in re.finditer(r"(?:^|\n)[0-9a-f]+:", flight_data):
            try:
                record, _ = decoder.raw_decode(flight_data, match.end())
            except json.JSONDecodeError:
                continue
            stack = [record]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    if all(field in value for field in fields):
                        return value
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)
        return None

    @staticmethod
    def _get_scoreboard(page):
        scoreboard = Statistic._get_page_data(page, ("scoreboardVisible", "rows", "problems"))
        if scoreboard is None:
            raise ExceptionParseStandings("DOJ scoreboard data not found")
        return scoreboard

    @staticmethod
    def _rating_fields(data):
        return {
            target: data[source]
            for source, target in (
                ("ratingBefore", "old_rating"),
                ("ratingAfter", "new_rating"),
                ("ratingDelta", "rating_change"),
                ("ratedPerformance", "performance"),
            )
            if data.get(source) is not None
        }

    def get_standings(self, users=None, statistics=None, **kwargs):
        contest = self._get_api(f"contests/{quote(self.key, safe='')}").get("contest")
        if not contest:
            raise ExceptionParseStandings("DOJ contest data not found")
        url = urljoin(self.url, f"/en/contests/{quote(self.key, safe='')}/standings")
        scoreboard = self._get_scoreboard(REQ.get(url))
        if not scoreboard["scoreboardVisible"]:
            raise ExceptionParseStandings("DOJ scoreboard is hidden")
        is_icpc = scoreboard["scoringMode"] == "ICPC"

        problems = {}
        for data in scoreboard["problems"]:
            code = urlsplit(data["href"]).path.rstrip("/").rsplit("/", 1)[-1]
            problem = {
                "short": data["shortLabel"],
                "name": data["title"] or data["subtitle"],
                "code": code,
                "url": urljoin(self.url, f"/en/problems/{code}"),
            }
            if not is_icpc:
                problem["full_score"] = data["maxScore"]
            try:
                metadata = self._get_api(f"problems/{code}")["problem"]
            except FailOnGetResponse as e:
                if e.code != 404:
                    raise
            else:
                problem["name"] = metadata["titles"].get("en") or metadata["titles"].get("ko") or problem["name"]
                for field in ("difficulty", "tags", "authors"):
                    if metadata.get(field) is not None:
                        problem[field] = metadata[field]
            problems[data["id"]] = problem

        result = {}
        grouped_team = False
        for data in scoreboard["rows"]:
            handle = data["displayName"]
            team = None
            profile_path = urlsplit(data.get("profileHref", "")).path
            if "/teams/" in profile_path:
                grouped_team = True
                team_url = urljoin(self.url, f"/en/teams/{profile_path.rstrip('/').rsplit('/', 1)[-1]}")
                team_data = self._get_page_data(REQ.get(team_url), ("team",))
                team = team_data.get("team") if team_data else None
                if not isinstance(team, dict) or not team.get("id") or not team.get("members"):
                    raise ExceptionParseStandings(f"DOJ team data not found: {handle}")
                members = [{"account": member["user"]["handle"]} for member in team["members"]]
                handles = [member["account"] for member in members]
            else:
                handles = [handle]
            if users is not None:
                handles = [member for member in handles if member in users]
            if not handles:
                continue
            row = {
                "place": data["rank"],
                "solving": data["totalScore"],
                "penalty": self.to_time(data["penaltySeconds"]),
                "problems": {},
            }
            if team is not None:
                row.update(team_id=team["id"], name=team["name"], _members=members, _account_url=team_url)
            if data.get("isScoreboardExcluded"):
                row["place"] = None
                row["_no_update_n_contests"] = True
            if data.get("teamLabel"):
                row["info"] = {"organization": data["teamLabel"]}
            if team is None and not data.get("isRatingPreview") and not data.get("isRatingPrediction"):
                for source, target in (("performance", "performance"), ("ratingDelta", "rating_change")):
                    if data.get(source) is not None:
                        row[target] = data[source]
            solved = 0
            for cell in data["cells"]:
                short = problems[cell["problemId"]]["short"]
                score, full_score = cell["score"], cell["maxScore"]
                attempts = cell["wrongAttempts"]
                problem = {}
                if is_icpc:
                    if score > 0:
                        problem["result"] = f"+{attempts}" if attempts else "+"
                    elif attempts:
                        problem["result"] = f"-{attempts}"
                    elif cell.get("pendingCount"):
                        problem["result"] = f"?{cell['pendingCount']}"
                    else:
                        continue
                else:
                    if score > 0 or attempts or cell.get("acceptedAtSeconds") is not None:
                        problem["result"] = score
                        if 0 < score < full_score:
                            problem["partial"] = True
                    elif cell.get("pendingCount"):
                        problem["result"] = f"?{cell['pendingCount']}"
                    else:
                        continue
                if score > 0 and score >= full_score:
                    solved += 1
                if cell.get("acceptedAtSeconds") is not None:
                    problem["time_in_seconds"] = cell["acceptedAtSeconds"]
                    problem["time"] = self.to_time(cell["acceptedAtSeconds"])
                if cell.get("isFirstSolve"):
                    problem["first_ac"] = True
                row["problems"][short] = problem
            row["solved"] = {"solving": solved}

            if team is None and contest["ratingEligible"] and contest["status"] == "ENDED":
                previous = (statistics or {}).get(handle, {})
                for field in ("old_rating", "new_rating", "rating_change", "performance", "is_rated", "unofficial"):
                    if field in previous:
                        row.setdefault(field, previous[field])
            for member in handles:
                result[member] = dict(deepcopy(row), member=member)

        return {
            "url": url,
            "result": result,
            "problems": list(problems.values()),
            "is_rated": contest["ratingEligible"],
            "standings_kind": "icpc" if is_icpc else "scoring",
            "hidden_fields": ["unofficial", "is_rated"],
            "grouped_team": grouped_team,
        }

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):
        for user in users:
            path = f"users/{quote(user, safe='')}"
            data = None
            try:
                data = Statistic._get_api(path)["user"]
                info = {k: v for k, v in data.items() if k not in ("avatarUrl", "countryCode", "organization")}
                info["country"] = data.get("countryCode")
                info["organization"] = data.get("organization")
                if data.get("avatarUrl"):
                    info["avatar"] = urljoin(resource.url, data["avatarUrl"])

                updates = {}
                for participation in Statistic._get_pages(f"{path}/contest-participations", "participations"):
                    fields = Statistic._rating_fields(participation)
                    fields.update(
                        is_rated=participation["ratingAfter"] is not None, unofficial=participation["isUnofficial"]
                    )
                    updates[participation["contest"]["slug"]] = fields
                for point in Statistic._get_pages(f"{path}/rating-history", "points"):
                    if not point.get("contest") or point["kind"] != "CONTEST":
                        continue
                    update = updates.setdefault(point["contest"]["slug"], {})
                    update.update(
                        old_rating=point["oldRating"], new_rating=point["newRating"], rating_change=point["delta"]
                    )
            except FailOnGetResponse as e:
                ret = {"delete": True} if e.code == 404 and data is None else {"skip": True, "delta": timedelta(days=1)}
            else:
                ret = {"info": info, "canonical_key": data["handle"]}
                if data["handle"] != user:
                    ret["rename"] = data["handle"]
                ret["contest_addition_update_params"] = {
                    "update": updates,
                    "by": "key",
                    "hidden_fields": ["unofficial", "is_rated"],
                }
            if pbar:
                pbar.update()
            yield ret
