import re
from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
from urllib.parse import quote, urlsplit

import arrow
from django.db import transaction

from clist.templatetags.extras import get_statistic_stats, is_improved_solution, is_solved
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseAccounts, ExceptionParseStandings, FailOnGetResponse
from ranking.utils import create_upsolving_statistic

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
    params = f"{'&' if '?' in url else '?'}page={page}"
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
            "standings_kind": "icpc" if format_type == "icpc" else "scoring",
            "problems": problems,
            "result": result,
            "submissions_info": submissions_info,
        }

    @staticmethod
    @transaction.atomic()
    def update_submissions(account, resource, with_submissions=False, **kwargs):
        info = deepcopy(account.submissions_info or {})
        last_id = info.get("last_submission_id", -1)
        pending_ids = set(info.get("pending_submission_ids", []))
        stop_id = min(last_id, min(pending_ids, default=last_id))
        newest_id = last_id
        count = info.get("count", 0)
        contests = {}
        problems = {}
        contest_formats = {}
        candidates = defaultdict(list)
        ret = defaultdict(int)

        def get_contest(key):
            key = str(key)
            if key not in contests:
                contests[key] = resource.contest_set.filter(key=key).first()
            return contests[key]

        url = f"{API_URL}submissions/?user={quote(account.key, safe='')}"
        page = 1
        previous_min_id = None
        total = None
        while True:
            data = get_page(url, page, page_size=SUBMISSIONS_PAGE_SIZE)
            if page == 1:
                total = data.get("total")
            if not isinstance(total, int) or total < 0 or data.get("total") != total:
                raise ExceptionParseAccounts(f"Submissions changed during pagination: {url}")
            submissions = data["data"]
            if not submissions:
                if total:
                    raise ExceptionParseAccounts(f"Empty submissions page: {url}&page={page}")
                break
            ids = [item["id"] for item in submissions]
            if ids != sorted(set(ids), reverse=True) or (previous_min_id is not None and ids[0] >= previous_min_id):
                raise ExceptionParseAccounts(f"Submissions out of order: {url}&page={page}")
            previous_min_id = ids[-1]
            newest_id = max(newest_id, ids[0])

            for item in submissions:
                submission_id = item["id"]
                if submission_id <= last_id and submission_id not in pending_ids:
                    continue
                if item.get("username", "").lower() != account.key.lower():
                    raise ExceptionParseAccounts(f"Unexpected submission user: {url}")
                if submission_id > last_id:
                    count += 1
                submission_time = arrow.get(item["created_at"]).datetime
                if account.last_submission is None or submission_time > account.last_submission:
                    account.last_submission = submission_time
                if not item.get("status") or item["status"] in PENDING_VERDICTS:
                    pending_ids.add(submission_id)
                    continue
                pending_ids.discard(submission_id)

                contest = get_contest(item["contest_id"]) if item.get("contest_id") is not None else None
                if item.get("contest_id") is not None and contest is None:
                    ret["missing_contests"] += 1
                    continue
                if contest is not None and submission_time < contest.end_time:
                    continue

                uid = item["problem_uid"]
                if uid not in problems:
                    problem_url = f"{API_URL}problems/{quote(uid, safe='')}/"
                    try:
                        problem_data = REQ.get(problem_url, headers=JSON_HEADERS, return_json=True)
                    except FailOnGetResponse as e:
                        if e.code != 404:
                            raise
                        problem_data = None
                    if problem_data is not None and (
                        not isinstance(problem_data, dict) or problem_data.get("uid") != uid
                    ):
                        raise ExceptionParseAccounts(f"Unexpected problem response: {problem_url}")
                    problems[uid] = problem_data
                problem_data = problems[uid]
                problem_path = urlsplit((problem_data or {}).get("url", "")).path
                match = re.fullmatch(r"/problems/([^/]+)/([^/]+)/?", problem_path)
                if not match:
                    ret["missing_problems"] += 1
                    continue
                contest_key, short = match.groups()
                if contest is None:
                    contest = get_contest(contest_key)
                if contest is None:
                    ret["missing_contests"] += 1
                    continue
                if submission_time < contest.end_time:
                    continue
                problem_info = next((p for p in contest.problems_list if p["short"] == short), None)
                if contest.key != contest_key or problem_info is None:
                    ret["missing_problems"] += 1
                    continue

                if contest.pk not in contest_formats:
                    format_type = {"icpc": "icpc", "scoring": "ioi"}.get(contest.standings_kind)
                    if format_type is None:
                        contest_url = f"{API_URL}contests/{quote(contest.key, safe='')}/"
                        contest_data = REQ.get(contest_url, headers=JSON_HEADERS, return_json=True)
                        format_type = contest_data.get("format_type") if isinstance(contest_data, dict) else None
                        if format_type not in {"icpc", "ioi"}:
                            raise ExceptionParseAccounts(f"Unexpected contest format: {contest_url}")
                    contest_formats[contest.pk] = format_type

                upsolving = parse_submission(item | {"language": item["language_name"], "verdict": item["status"]})
                accepted = item["status"] == "Accepted"
                if contest_formats[contest.pk] == "ioi":
                    if accepted:
                        full_score = problem_info.get("full_score")
                        if not isinstance(full_score, (int, float)) or full_score <= 0:
                            raise ExceptionParseAccounts(f"Missing full score: contest={contest.key}, problem={short}")
                        upsolving["result"] = full_score
                    else:
                        upsolving.update(result=0, partial=True)
                else:
                    upsolving["result"] = "+" if accepted else "-"
                upsolving["submission_time"] = submission_time.timestamp()
                candidates[contest].append((short, upsolving))
                if with_submissions:
                    ret.setdefault("submissions", []).append({
                        "contest": contest,
                        "problem": problem_info,
                        "info": upsolving,
                    })

            if ids[-1] <= stop_id or page >= data["pagesCount"]:
                break
            page += 1

        # Fetch and lock fresh statistics only after all HTTP requests have finished.
        ret["n_contests"] = 0
        for contest in sorted(candidates, key=lambda c: c.pk):
            statistic, _ = create_upsolving_statistic(
                resource=resource, contest=contest, account=account, select_for_update=True
            )
            updated = False
            for short, upsolving in candidates[contest]:
                problem = statistic.addition.setdefault("problems", {}).setdefault(short, {})
                if is_solved(problem):
                    continue
                previous = problem.get("upsolving", {})
                # The account API has no scores, so a rejection cannot replace a known partial score.
                if previous.get("partial") and not is_solved(upsolving):
                    continue
                if not is_improved_solution(upsolving, previous):
                    continue
                problem["upsolving"] = upsolving
                updated = True
                ret["n_updated"] += 1

            if updated:
                update_fields = ["addition"]
                for field, value in get_statistic_stats(statistic.addition, solving=statistic.solving).items():
                    if getattr(statistic, field) != value:
                        setattr(statistic, field, value)
                        update_fields.append(field)
                statistic.save(update_fields=update_fields)
                ret["n_contests"] += 1
        info.update(last_submission_id=newest_id, count=count)
        if pending_ids:
            info["pending_submission_ids"] = sorted(pending_ids)
        else:
            info.pop("pending_submission_ids", None)
        account.submissions_info = info
        account.save(update_fields=["submissions_info", "last_submission"])
        return ret

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
