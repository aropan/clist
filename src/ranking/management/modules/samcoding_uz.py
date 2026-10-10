import re
from copy import deepcopy
from datetime import timedelta
from urllib.parse import quote

from clist.templatetags.extras import is_improved_solution
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseAccounts, ExceptionParseStandings, FailOnGetResponse

API_URL = "https://samcoding.uz/api/"
JSON_HEADERS = {"Accept": "application/json", "Accept-Language": "en"}
SUBMISSIONS_PAGE_SIZE = 100
UPSOLVING_VERSION = 1
PENDING_VERDICTS = {"Waiting", "Pending", "In Queue", "Queued", "Running", "Compiling"}


def parse_verdict(value):
    if not isinstance(value, str) or not value:
        return {"verdict": value}
    match = re.fullmatch(r"(.+?)(?:\s+#(\d+))?", value)
    name, test = match.groups()
    if name == "Accepted":
        verdict = "AC"
    elif name.isupper():
        verdict = name
    else:
        verdict = "".join(word[0].upper() for word in name.split())
    parsed = {"verdict": verdict, "verdict_full": value}
    if test is not None:
        parsed["test"] = int(test)
    return parsed


def get_page(url, page, *, page_size=None):
    params = f"?page={page}"
    if page_size:
        params += f"&pageSize={page_size}"
    data = REQ.get(url + params, headers=JSON_HEADERS, return_json=True)
    if (
        not isinstance(data, dict)
        or data.get("page") != page
        or not isinstance(data.get("pagesCount"), int)
        or not isinstance(data.get("data"), list)
    ):
        raise ExceptionParseStandings(f"Unexpected API page: {url}{params}")
    return data


def parse_submission(item):
    return {
        "submission_id": item["id"],
        "language": item["language"],
        "exec_time": f"{item['time_used']} ms",
        "memory_usage": f"{item['memory_used']} KB",
        **parse_verdict(item["verdict"]),
    }


class Statistic(BaseModule):
    def get_standings(self, users=None, statistics=None, **kwargs):
        contest_url = f"{API_URL}contests/{quote(str(self.key), safe='')}/"
        contest_data = REQ.get(contest_url, headers=JSON_HEADERS, return_json=True)
        if not isinstance(contest_data, dict) or not isinstance(contest_data.get("problems"), list):
            raise ExceptionParseStandings(f"Unexpected contest response: {contest_url}")
        if contest_data.get("status") == "upcoming":
            return {"action": "skip"}
        format_type = contest_data.get("format_type")
        if format_type not in {"icpc", "ioi"}:
            raise ExceptionParseStandings(f"Unexpected contest format: {format_type}")

        clist_url = contest_url + "clist-standings/"
        clist_data = REQ.get(clist_url, headers=JSON_HEADERS, return_json=True)
        if (
            not isinstance(clist_data, dict)
            or clist_data.get("status") != "ok"
            or not isinstance(clist_data.get("problems"), list)
            or not isinstance(clist_data.get("standings"), list)
        ):
            raise ExceptionParseStandings(f"Unexpected standings response: {clist_url}")
        clist_problems = {item["short"]: item for item in clist_data["problems"]}
        clist_rows = {item["member"]: item for item in clist_data["standings"]}

        problems = []
        full_scores = {}
        for item in contest_data["problems"]:
            short = item["letter"]
            problems.append({
                "short": short,
                "name": item["problem_title"],
                "url": item["url"],
                "full_score": item["score"],
            })
            for field in ("archive_url", "tags"):
                if value := clist_problems.get(short, {}).get(field):
                    problems[-1][field] = value
            full_scores[short] = item["score"]

        standings_url = contest_url + "standings/"
        result = {}
        page = 1
        while True:
            data = get_page(standings_url, page)
            for item in data["data"]:
                member = item.get("username")
                if not member:
                    raise ExceptionParseStandings(f"Missing username on {standings_url}?page={page}")
                if member not in clist_rows:
                    raise ExceptionParseStandings(f"Missing member {member} on {clist_url}")
                row = result.setdefault(member, {"member": member})
                row["place"] = clist_rows[member]["place"]
                if row["place"] is None:
                    row["_no_update_n_contests"] = True
                if format_type == "icpc":
                    row["solving"] = item["solved_count"]
                    row["penalty"] = item["penalty"]
                else:
                    row["solving"] = item["total_score"]
                    row["solved_count"] = item["solved_count"]
                if name := " ".join(filter(None, (item.get("first_name"), item.get("last_name")))):
                    row["name"] = name
                if country := item.get("country_code"):
                    row["country"] = country.upper()

                row_problems = row.setdefault("problems", {})
                for short, task in item["problems_data"].items():
                    if short not in full_scores:
                        raise ExceptionParseStandings(f"Unknown problem {short} on {standings_url}")
                    attempts = task["attempts"]
                    if format_type == "icpc":
                        if task["solved"]:
                            problem = {"result": "+" if attempts == 1 else f"+{attempts - 1}"}
                        else:
                            problem = {"result": f"-{attempts}"}
                    else:
                        problem = {"result": task["score"], "attempts": attempts}
                        if not task["solved"]:
                            problem["partial"] = True
                    if task.get("time") is not None and (format_type == "ioi" or task["solved"]):
                        problem["time"] = self.to_time(task["time"], 2)
                    old_problem = (statistics or {}).get(member, {}).get("problems", {}).get(short, {})
                    if old_problem.get("result") == problem["result"]:
                        for field in (
                            "submission_id",
                            "language",
                            "verdict",
                            "verdict_full",
                            "test",
                            "exec_time",
                            "memory_usage",
                        ):
                            if field in old_problem:
                                problem[field] = old_problem[field]
                        if old_problem.get("verdict"):
                            problem.update(parse_verdict(old_problem.get("verdict_full", old_problem["verdict"])))
                    row_problems[short] = problem

            if page >= data["pagesCount"]:
                break
            page += 1

        for member, old_row in (statistics or {}).items():
            for short, old_problem in old_row.get("problems", {}).items():
                if short not in full_scores or "upsolving" not in old_problem:
                    continue
                row = result.setdefault(member, {"member": member, "place": None, "_no_update_n_contests": True})
                problem = row.setdefault("problems", {}).setdefault(short, {})
                problem["upsolving"] = deepcopy(old_problem["upsolving"])

        submissions_info = deepcopy(getattr(self.contest, "submissions_info", {}) or {})
        if submissions_info.get("upsolving_version") != UPSOLVING_VERSION:
            submissions_info = {"upsolving_version": UPSOLVING_VERSION}
        last_submission_id = submissions_info.get("last_submission_id", -1)
        pending_submission_ids = set(submissions_info.get("pending_submission_ids", []))
        stop_id = min(last_submission_id, min(pending_submission_ids, default=last_submission_id))
        submissions_url = contest_url + "submissions/"
        metadata = get_page(submissions_url, 1, page_size=1)
        total = metadata.get("total")
        if not isinstance(total, int) or total < 0:
            raise ExceptionParseStandings(f"Unexpected submissions count: {submissions_url}")
        last_page = (total + SUBMISSIONS_PAGE_SIZE - 1) // SUBMISSIONS_PAGE_SIZE
        if total:
            latest = get_page(submissions_url, total, page_size=1)["data"]
            if len(latest) != 1 or not isinstance(latest[0].get("id"), int):
                raise ExceptionParseStandings(f"Unexpected latest submission: {submissions_url}")
            if latest[0]["id"] <= last_submission_id and not pending_submission_ids:
                last_page = 0
        newest_id = last_submission_id
        new_count = 0
        previous_min_id = None
        for page in range(last_page, 0, -1):
            data = get_page(submissions_url, page, page_size=SUBMISSIONS_PAGE_SIZE)
            submissions = data["data"]
            if data.get("total") != total:
                raise ExceptionParseStandings(f"Submissions changed during pagination: {submissions_url}")
            if not submissions:
                raise ExceptionParseStandings(f"Empty submissions page: {submissions_url}?page={page}")
            ids = [item["id"] for item in submissions]
            if ids != sorted(ids) or (previous_min_id is not None and ids[-1] >= previous_min_id):
                raise ExceptionParseStandings(f"Submissions out of order: {submissions_url}?page={page}")
            previous_min_id = ids[0]
            newest_id = max(newest_id, ids[-1])
            for item in submissions:
                if item["id"] <= last_submission_id and item["id"] not in pending_submission_ids:
                    continue
                if item["id"] > last_submission_id:
                    new_count += 1
                if item.get("verdict") in PENDING_VERDICTS:
                    pending_submission_ids.add(item["id"])
                    continue
                pending_submission_ids.discard(item["id"])
                member = item.get("username")
                short = item.get("problem")
                if not member or short not in full_scores:
                    continue
                is_upsolve = item.get("is_upsolve")
                if is_upsolve is None:
                    is_upsolve = item.get("relative_time_seconds", 0) > self.contest.duration.total_seconds()
                if is_upsolve:
                    row = result.setdefault(member, {"member": member, "place": None, "_no_update_n_contests": True})
                    problem = row.setdefault("problems", {}).setdefault(short, {})
                    upsolving = parse_submission(item)
                    if format_type == "icpc":
                        upsolving["result"] = "+" if item.get("verdict") == "Accepted" else "-"
                    else:
                        upsolving["result"] = item["score"]
                        if item["score"] < full_scores[short]:
                            upsolving["partial"] = True
                    previous = problem.get("upsolving", {})
                    if (
                        not previous
                        or is_improved_solution(upsolving, previous)
                        or (
                            upsolving["result"] == previous.get("result")
                            and upsolving.get("partial") == previous.get("partial")
                            and item["id"] > previous.get("submission_id", -1)
                        )
                    ):
                        problem["upsolving"] = upsolving
                    continue
                row = result.get(member)
                if row is None:
                    continue
                problem = row.get("problems", {}).get(short)
                if problem is None or "result" not in problem:
                    continue
                if format_type == "icpc":
                    solved = problem["result"].startswith("+")
                    accepted = item.get("verdict") == "Accepted"
                    if solved != accepted:
                        continue
                elif problem["result"] != item.get("score"):
                    continue
                if item["id"] <= problem.get("submission_id", -1):
                    continue
                problem.pop("test", None)
                problem.update(parse_submission(item))
            if ids[0] <= stop_id:
                break
        if newest_id > last_submission_id:
            submissions_info["last_submission_id"] = newest_id
            submissions_info["count"] = submissions_info.get("count", 0) + new_count
        if pending_submission_ids:
            submissions_info["pending_submission_ids"] = sorted(pending_submission_ids)
        else:
            submissions_info.pop("pending_submission_ids", None)

        return {
            "url": clist_data["url"],
            "problems": problems,
            "result": result,
            "submissions_info": submissions_info,
        }

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):
        for member in users:
            url = f"{API_URL}users/{quote(member, safe='')}/"
            try:
                data = REQ.get(url, headers=JSON_HEADERS, return_json=True)
            except FailOnGetResponse as e:
                if e.code == 404:
                    yield {"delete": True}
                else:
                    yield {"skip": True, "delta": timedelta(days=1)}
                if pbar:
                    pbar.update()
                continue

            if not isinstance(data, dict) or data.get("username", "").lower() != member.lower():
                raise ExceptionParseAccounts(f"Unexpected profile response: {url}")
            info = {"name": " ".join(filter(None, (data.get("first_name"), data.get("last_name"))))}
            for field in ("avatar", "country", "city", "school", "first_name", "last_name", "tg_link", "cf_link"):
                if data.get(field):
                    info[field] = data[field]
            if isinstance(data.get("rating"), dict):
                for field in ("rating", "max_rating", "rating_color", "rating_name"):
                    if data["rating"].get(field) is not None:
                        info[field] = data["rating"][field]

            ret = {"info": info, "canonical_key": data["username"]}
            if member != data["username"]:
                ret["rename"] = data["username"]
            if info.get("rating") is not None:
                history_url = f"https://samcoding.uz/profile/{quote(member, safe='')}/rating-history"
                try:
                    history = REQ.get(history_url, headers=JSON_HEADERS, return_json=True)
                except FailOnGetResponse as e:
                    if e.code == 404:
                        history = []
                    else:
                        yield {"skip": True, "delta": timedelta(days=1)}
                        if pbar:
                            pbar.update()
                        continue
                if not isinstance(history, list):
                    raise ExceptionParseAccounts(f"Unexpected rating history response: {history_url}")
                updates = {}
                for item in history:
                    if item.get("rank") is None or not item.get("contest") or item.get("rating") is None:
                        continue
                    rating = item["rating"]
                    change = item.get("change")
                    update = {"new_rating": rating}
                    if change is not None:
                        update["old_rating"] = rating - change
                        update["rating_change"] = change
                    updates[item["contest"]] = update
                if updates:
                    ret["contest_addition_update_params"] = {
                        "update": updates,
                        "by": "title",
                        "clear_rating_change": True,
                    }
            if pbar:
                pbar.update()
            yield ret
