import json
import re
from itertools import count
from urllib.parse import quote, urlencode, urljoin

from flatten_dict import flatten

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseAccounts, ExceptionParseStandings, FailOnGetResponse
from utils.timetools import parse_datetime


class Statistic(BaseModule):
    def get_standings(self, users=None, statistics=None, **kwargs):
        number = self.info["parse"]["contestNumber"]
        contest_url = self.url.rstrip("/")
        api_url = urljoin(contest_url, f"/api/contests/{number}/ranking")
        selected = set(users) if users is not None else None
        result = {}
        seen = set()
        hidden_fields = set()
        for page in count(1):
            params = urlencode({"type": "contest", "page": page, "pageSize": 100})
            data = REQ.get(f"{api_url}?{params}", return_json=True)
            pagination = data["pagination"]
            if page == 1:
                total_pages = pagination["totalPages"]
                total_participants = data["totalParticipants"]
            elif pagination["totalPages"] != total_pages or data["totalParticipants"] != total_participants:
                raise ExceptionParseStandings(f"Repovive pagination changed on page {page}")
            if pagination["page"] != page or ((page > 1 or total_pages > 1) and not data["rankings"]):
                raise ExceptionParseStandings(f"Invalid Repovive pagination on page {page}")

            if page == 1:
                standings_kind = {"codeforces": "cf", "fixed": "scoring"}[data["scoringType"]]
                raw_info = {k: v for k, v in data.items() if not isinstance(v, (list, dict))}
                problems = [
                    {
                        "short": problem["letter"],
                        "name": problem["title"],
                        "full_score": problem["points"],
                        "url": f"{contest_url}/problems/{quote(problem['letter'], safe='')}",
                    }
                    for problem in data["problems"]
                ]

            for item in data["rankings"]:
                item = dict(item)
                member = str(item.pop("odId"))
                if member in seen:
                    raise ExceptionParseStandings(f"Repeated Repovive participant on page {page}: {member}")
                seen.add(member)
                if selected is not None and member not in selected:
                    continue
                row = {
                    "member": member,
                    "place": item.pop("rank"),
                    "name": item.pop("userName"),
                    "solving": item.pop("totalScore"),
                    "solved": {"solving": item.pop("problemsSolved")},
                    "problems": {},
                }
                if country := item.pop("country", None):
                    row["country"] = country
                if avatar := item.pop("userPicture", None):
                    row["info"] = {"avatar_url": avatar}
                last_accepted = item.pop("lastAcceptedAt")
                if last_accepted and row["solved"]["solving"]:
                    last_activity = parse_datetime(last_accepted)
                    row["last_activity"] = last_activity
                    row["_last_submit_time"] = last_activity.timestamp()

                solved = set(item.pop("solvedProblems"))
                for cell in item.pop("problemScores"):
                    short = cell["letter"]
                    wrongs = cell["wrongs"]
                    if short in solved:
                        minutes = cell["time"]
                        problem = {
                            "result": cell["score"],
                            "time_in_seconds": minutes * 60,
                            "time": self.to_time(minutes, num=2),
                        }
                        if wrongs:
                            problem["penalty_score"] = wrongs
                    else:
                        if not wrongs:
                            continue
                        problem = {"result": f"-{wrongs}"}
                    row["problems"][short] = problem

                previous = (statistics or {}).get(member, {})
                for field in ("old_rating", "new_rating", "rating_change", "performance"):
                    if field in previous:
                        row[field] = previous[field]
                item.pop("rating")
                rating_delta = item.pop("ratingDelta")
                if rating_delta is not None and "new_rating" not in row:
                    row["rating_change"] = rating_delta
                identity = item.pop("identityMarks")
                extra = flatten({"identityMarks": identity}, reducer="underscore")
                extra.update({k: v for k, v in item.items() if not isinstance(v, (list, dict))})
                row.update(extra)
                hidden_fields.update(extra)
                result[member] = row

            if page >= total_pages:
                break

        if len(seen) != total_participants:
            raise ExceptionParseStandings(
                f"Incomplete Repovive standings: expected {total_participants} participants, got {len(seen)}"
            )

        return {
            "url": f"{contest_url}/ranking",
            "result": result,
            "problems": problems,
            "standings_kind": standings_kind,
            "raw_info": raw_info,
            "hidden_fields": sorted(hidden_fields),
        }

    @staticmethod
    def _get_profile(page):
        chunks = []
        for match in re.finditer(r"<script[^>]*>\s*self\.__next_f\.push\((\[.*?\])\)\s*</script>", page, re.S):
            chunk = json.loads(match[1])
            if chunk[0] == 1:
                chunks.append(chunk[1])
        flight_data = "".join(chunks)
        decoder = json.JSONDecoder(object_hook=lambda obj: {k: v for k, v in obj.items() if v != "$undefined"})
        for match in re.finditer(r"(?:^|\n)[0-9a-f]+:", flight_data):
            try:
                record, _ = decoder.raw_decode(flight_data, match.end())
            except json.JSONDecodeError:
                continue
            stack = [record]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    if "user" in value and "initialRatingHistory" in value:
                        return value
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)
        raise ExceptionParseAccounts("Repovive profile data not found")

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):
        rating_fields = {"current": "rating", "max": "max_rating"}
        for user in users:
            url = urljoin(resource.url, f"/users/{quote(user, safe='')}")
            try:
                page = REQ.get(url)
            except FailOnGetResponse as exc:
                if exc.code != 404:
                    raise
                ret = {"delete": True}
            else:
                profile = Statistic._get_profile(page)
                info = {
                    k: v
                    for k, v in profile["user"].items()
                    if k not in ("email", "fieldVisibility", "isFollowing", "documents")
                }
                assert info["_id"] == user
                rating = info.pop("rating") or {}
                for key, value in rating.items():
                    info[rating_fields.get(key, key)] = value
                if avatar := info.pop("avatar", None):
                    info["avatar_url"] = urljoin(resource.url, avatar)

                updates = {}
                for point in profile["initialRatingHistory"]:
                    updates[point["contestNumber"]] = {
                        "old_rating": point["rating"] - point["delta"],
                        "new_rating": point["rating"],
                        "rating_change": point["delta"],
                        "performance": point["performanceRating"],
                        "_rank": point["rank"],
                    }
                ret = {
                    "info": info,
                    "canonical_key": info["_id"],
                    "contest_addition_update_params": {"update": updates, "by": "info__parse__contestNumber"},
                }
            if pbar:
                pbar.update()
            yield ret
