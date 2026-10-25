from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from datetime import datetime, timedelta
from itertools import count
from threading import Lock
from urllib.parse import quote

from django.utils import timezone

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseAccounts, ExceptionParseStandings, FailOnGetResponse
from utils.ratelimiter import RateLimiter

API_URL = "https://codearena.uz/api/v1/"
HEADERS = {"Accept": "application/json", "Accept-Language": "en"}
RULES = {"icpc": "icpc", "cf": "cf", "score": "scoring"}
RATING_FIELDS = {"rating_before": "old_rating", "rating_after": "new_rating", "rating_change": "rating_change"}
request_limiter = RateLimiter(max_calls=1, period=1)
request_lock = Lock()


def get_json(url):
    with request_lock, request_limiter:
        pass  # Reserve the next request slot before starting network I/O.
    return REQ.get(url, headers=HEADERS, return_json=True, raise_codes={404, 429}, n_attempts=1)


def pages(url, error):
    for page in count(1):
        page_url = f"{url}?page={page}&page_size=200"
        try:
            data = get_json(page_url)
        except (FailOnGetResponse, ValueError) as exc:
            raise error(f"Failed to load {page_url}: {exc}") from exc
        if not data or data.get("status") != "ok":
            raise error(f"Unexpected API response on {page_url}")
        yield data
        if page >= data["pagesCount"]:
            break


class Statistic(BaseModule):
    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):
        profile_limiter = RateLimiter(max_calls=1, period=2)
        profile_lock = Lock()

        def fetch_profile(member):
            with profile_lock, profile_limiter:
                pass
            url = f"{API_URL}users/{quote(member, safe='')}/"
            try:
                try:
                    response = get_json(url)
                except FailOnGetResponse as exc:
                    if exc.code != 404:
                        raise
                    return {"delete": True}
                if not response or response.get("status") != "ok":
                    raise ExceptionParseAccounts(f"Unexpected profile response on {url}")
                profile = response["user"]
                canonical = profile.get("username") or member
                updates = {}
                history_url = f"{API_URL}users/{quote(canonical, safe='')}/ratings/"
                for data in pages(history_url, ExceptionParseAccounts):
                    for item in data["data"]:
                        updates[str(item["contest_id"])] = {
                            target: item[source]
                            for source, target in RATING_FIELDS.items()
                            if item.get(source) is not None
                        }
                ret = {
                    "info": dict(profile),
                    "canonical_key": canonical,
                    "contest_addition_update_params": {"update": updates, "by": "key"},
                }
                if name := profile.get("name"):
                    ret["info"].setdefault("full_name", name)
                if canonical != member:
                    ret["rename"] = canonical
                return ret
            except FailOnGetResponse, ExceptionParseAccounts, KeyError, ValueError:
                return {"skip": True, "delta": timedelta(hours=1)}

        with PoolExecutor(max_workers=8) as executor:
            for ret in executor.map(fetch_profile, users):
                if pbar:
                    pbar.update()
                yield ret

    @staticmethod
    def _problems(items):
        problems = []
        for item in items:
            problem = dict(item)
            problem["short"] = problem.pop("label")
            for source, target in (("title", "name"), ("slug", "code"), ("points", "full_score")):
                if source in problem:
                    problem[target] = problem.pop(source)
            problems.append(problem)
        return problems

    @staticmethod
    def _row(item, contest):
        row = {
            "member": item["member"],
            "place": item.get("place"),
            "solving": item["solved"] if contest["rules"] == "icpc" else item["score"],
            "problems": {},
        }
        for field in ("name", "country", "penalty", "author", "disqualified", "out_of_competition"):
            if item.get(field) is not None:
                row[field] = item[field]
        if item.get("solved") is not None:
            row["solved"] = {"solving": item["solved"]}
        excluded = item.get("author") or item.get("disqualified")
        rated = contest["is_rated"] and not (excluded or item.get("out_of_competition"))
        if excluded:
            row.update(place=None, _no_update_n_contests=True)
        if not rated:
            row["is_rated"] = False
        if rated and contest.get("rating_applied"):
            row.update({
                target: item[source] for source, target in RATING_FIELDS.items() if item.get(source) is not None
            })
        for short, cell in (item.get("problems") or {}).items():
            accepted = str(cell["result"]).startswith("+")
            output = dict(cell)
            points = output.pop("points", 0)
            if contest["rules"] != "icpc" and (accepted or points > 0):
                output["result"] = points
                if accepted:
                    output["result_verdict"] = "accepted"
                    if contest["rules"] == "cf":
                        output["penalty_score"] = cell.get("wrong_tries", 0)
                else:
                    output["partial"] = True
            minutes = output.pop("minutes", None)
            if minutes is not None:
                output["time_in_seconds"] = minutes * 60
            first_solve = output.pop("first_solve", None)
            if first_solve is not None:
                output["first_ac"] = first_solve
            if solved_at := cell.get("solved_at"):
                last_activity = datetime.fromisoformat(solved_at)
                row["last_activity"] = max(row.get("last_activity", last_activity), last_activity)
            row["problems"][short] = output
        return row

    def get_standings(self, users=None, statistics=None, **kwargs):
        url = f"{API_URL}contests/{quote(str(self.key), safe='')}/standings/"
        first = None
        result = {}
        for data in pages(url, ExceptionParseStandings):
            if first is None:
                first = data
                contest = data["contest"]
                if contest["rules"] not in RULES:
                    raise ExceptionParseStandings(f"Unknown rules '{contest['rules']}' for contest {self.key}")
            for item in data["data"]:
                row = self._row(item, contest)
                if not row["problems"] and not any(field in row for field in ("new_rating", "rating_change")):
                    continue
                result[row["member"]] = row
        minutes = contest.get("personal_minutes")
        minutes = contest["duration_minutes"] if minutes is None else minutes
        metadata = {
            "url": contest["standings_url"],
            "kind": contest["kind"],
            "standings_kind": RULES[contest["rules"]],
            "duration_in_secs": int(minutes * 60),
            "is_rated": contest["is_rated"],
            "writers": contest.get("authors"),
            "writers_case_sensitive": True,
            "has_hidden_results": first.get("hidden", False),
        }
        if metadata["writers"] == getattr(self, "info", {}).get("writers"):
            # None reconciles existing metadata with writer relations, even on first import.
            metadata["writers"] = None
        unavailable = metadata["has_hidden_results"] or contest.get("status") == "upcoming"
        if unavailable or (contest["is_rated"] and not contest.get("rating_applied")):
            end = datetime.fromisoformat(contest["end_time"])
            delay = max(end - timezone.now() + timedelta(minutes=10), timedelta(hours=1))
            metadata.update(timing_statistic_delta=delay, force_timing_statistic_delta=True)
        if unavailable:
            return {**metadata, "action": "skip", "keep_results": True}
        if users is not None:
            selected = set(users)
            result = {member: row for member, row in result.items() if member in selected}
        return {
            **metadata,
            "result": result,
            "problems": self._problems(first["problems"]),
            "hidden_fields": ["author", "disqualified", "out_of_competition", "is_rated"],
        }
