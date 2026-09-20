#!/usr/bin/env python3

import html
import json
import re
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import arrow
from django.db import transaction
from django.db.models import OuterRef
from sql_util.utils import Exists

from clist.templatetags.extras import (
    get_item,
    get_problem_key,
    get_problem_name,
    get_problem_short,
    is_improved_solution,
    is_solved,
)
from logify import live as tqdm
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseAccounts, ExceptionParseStandings, FailOnGetResponse
from ranking.utils import create_upsolving_statistic
from utils.ratelimiter import RateLimiter

LOCALE_HEADERS = {"X-LANG": "en"}

VERDICT_TEXTS = {
    0: "Waiting",
    1: "Running",
    2: "Compiling",
    3: "Runtime error",
    4: "Memory limit",
    5: "Compilation error",
    6: "Presentation error",
    7: "Time limit",
    8: "Wrong answer",
    9: "Accepted",
    10: "Partially accepted",
    11: "Checker error",
    12: "Invalid solution",
}
VERDICTS_WITH_TEST = {1, 3, 4, 6, 7, 8}
PENDING_STATUSES = {0, 1, 2}
ACCEPTED_STATUS = 9


def parse_inertia_page(page, url):
    for match in re.finditer(r'<script[^>]*type="application/json"[^>]*>(?P<data>.*?)</script>', page, re.DOTALL):
        try:
            data = json.loads(match.group("data"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "component" in data:
            return data
    match = re.search(r'data-page="(?P<data>[^"]*)"', page)
    if match:
        return json.loads(html.unescape(match.group("data")))
    raise ExceptionParseStandings(f"Failed to find inertia page data: {url}")


def get_page_data(url, ignore_codes=None):
    page, code = REQ.get(url, headers=dict(LOCALE_HEADERS), return_code=True, ignore_codes=ignore_codes)
    if code != 200 or not page:
        return None
    return parse_inertia_page(page, url)


def get_props(data, url):
    props = data.get("props") if isinstance(data, dict) else None
    if not isinstance(props, dict):
        raise ExceptionParseStandings(f"Failed to find props: {url}")
    return props


def get_tab_data(props, tab, url):
    if props.get("tab") != tab:
        raise ExceptionParseStandings(f'Expected "{tab}" tab, got "{props.get("tab")}": {url}')
    tab_data = props.get("tabData")
    if not isinstance(tab_data, dict):
        raise ExceptionParseStandings(f'Failed to find "{tab}" tab data: {url}')
    return tab_data


def get_submissions_pagination(props, url):
    tab_data = props.get("tabData")
    pagination = tab_data.get("pagination") if isinstance(tab_data, dict) else props.get("pagination")
    if not isinstance(pagination, dict) or not isinstance(pagination.get("items"), list):
        raise ExceptionParseStandings(f"Failed to find submissions pagination: {url}")
    return pagination


def next_submissions_url(pagination, base_url, tab):
    # nextUrl drops the tab that selects submissions and can carry a proxy-downgraded scheme.
    next_url = pagination.get("nextUrl")
    if not next_url:
        return None
    parsed, base = urlparse(next_url), urlparse(base_url)
    query = dict(parse_qsl(parsed.query))
    if tab:
        query["tab"] = tab
    return urlunparse(parsed._replace(scheme=base.scheme, netloc=base.netloc, query=urlencode(query)))


def parse_submission(item):
    handle = get_item(item, "user.username")
    if not handle:
        return None

    status = item["status"]
    verdict = VERDICT_TEXTS.get(status, "Undefined status")
    is_accepted = status == ACCEPTED_STATUS

    submission = {
        "handle": handle,
        "task_name": get_item(item, "task.title"),
        "upsolving": bool(item.get("isUpsolve")),
        "binary": is_accepted,
        "exec_time": f"{item['runTime']} ms",
        "memory_usage": f"{item['runMemory']} KB",
        "id": item["id"],
        "language": get_item(item, "language.name"),
        "submission_time": int(arrow.get(item["createdAt"]).timestamp()),
        "verdict_full": verdict,
        "verdict": "AC" if is_accepted else "".join(w[0].upper() for w in verdict.split()),
    }

    if task_number := get_item(item, "task.number"):
        submission["task_id"] = task_number
    if status in VERDICTS_WITH_TEST and item.get("activeTest") is not None:
        submission["test"] = item["activeTest"]

    return submission


def process_submissions_url(attempts_url, submissions_info, n_pages=-1):
    last_submission_id = submissions_info.setdefault("last_submission_id", -1)
    submissions_info.setdefault("count", 0)
    pending_submission_ids = set(submissions_info.get("pending_submission_ids", []))
    stop_id = min(last_submission_id, min(pending_submission_ids) - 1) if pending_submission_ids else last_submission_id

    url = attempts_url
    progress_bar = tqdm.tqdm(desc="submissions fetching")
    while n_pages and url:
        n_pages -= 1

        data = get_page_data(url)
        if data is None:
            raise ExceptionParseStandings(f"Failed to get submissions page: {url}")
        props = get_props(data, url)
        pagination = get_submissions_pagination(props, url)

        n_seen = 0
        for item in pagination["items"]:
            submission = parse_submission(item)
            if submission is None:
                continue
            submission_id = submission["id"]
            if submission_id <= stop_id:
                progress_bar.close()
                return
            n_seen += 1
            if submission_id <= last_submission_id and submission_id not in pending_submission_ids:
                continue
            if submission_id > submissions_info["last_submission_id"]:
                submissions_info["last_submission_id"] = submission_id
                submissions_info["last_submission_time"] = arrow.get(submission["submission_time"]).isoformat()
                submissions_info["time"] = arrow.now().isoformat()
            if item["status"] in PENDING_STATUSES:
                pending_submission_ids.add(submission_id)
                submissions_info["pending_submission_ids"] = sorted(pending_submission_ids)
                continue
            if submission_id in pending_submission_ids:
                pending_submission_ids.remove(submission_id)
                if pending_submission_ids:
                    submissions_info["pending_submission_ids"] = sorted(pending_submission_ids)
                else:
                    submissions_info.pop("pending_submission_ids", None)
            submissions_info["count"] += 1
            yield submission
        progress_bar.update(n_seen)
        if not n_seen:
            break

        url = next_submissions_url(pagination, attempts_url, props.get("tab"))
    progress_bar.close()


def process_submission_problem(submission, upsolving, short, addition):
    problems = addition.setdefault("problems", {})
    problem = problems.setdefault(short, {})
    if upsolving:
        if is_solved(problem):
            return False
        problem = problem.setdefault("upsolving", {})
    if is_improved_solution(submission, problem):
        if "result" in problem:
            submission.pop("binary")
        problem.update(submission)
        return True
    return False


class Statistic(BaseModule):
    def get_standings(self, users=None, statistics=None, **kwargs):
        standings_url = self.url.rstrip("/") + "/results"

        problems_infos = OrderedDict()
        first_ac_user_ids = {}
        result = OrderedDict()

        n_page = 0
        last_page = 1
        progress_bar = tqdm.tqdm(desc="results pagination")
        while n_page < last_page:
            n_page += 1
            page_url = f"{standings_url}?page={n_page}"

            data = get_page_data(page_url)
            if data is None:
                raise ExceptionParseStandings(f"Failed to get standings page: {page_url}")
            standings = get_tab_data(get_props(data, page_url), "standings", page_url)
            last_page = standings.get("lastPage") or 1
            progress_bar.update()

            is_ioi = standings.get("contestMode") == "ioi"
            tasks = standings.get("tasks") or []

            for task in tasks:
                short = task["letter"]
                if short not in problems_infos:
                    problems_infos[short] = {
                        "short": short,
                        "name": task.get("title") or short,
                        "url": urljoin(standings_url, f"tasks/{task['letter']}"),
                        "full_score": task["maxScore"],
                    }
                    first_ac_user_ids[short] = task.get("firstSolvedUserId")

            for row_data in standings.get("standings") or []:
                handle = row_data.get("participantUsername") or row_data.get("participantName")
                if not handle:
                    continue

                r = result.setdefault(handle, OrderedDict())
                r["member"] = handle
                r["place"] = row_data.get("rankRange") or row_data["rank"]
                r["solving"] = row_data["score"]
                if not is_ioi:
                    r["penalty"] = row_data["penalty"]
                    if row_data.get("solvedCount") is not None:
                        r["tasks"] = str(row_data["solvedCount"])
                if name := row_data.get("participantName"):
                    r["name"] = name
                if study := row_data.get("study"):
                    r["affiliation"] = study
                if row_data.get("kicked"):
                    r["_no_update_n_contests"] = True
                    r.pop("place", None)

                if rating_change := row_data.get("ratingChange"):
                    if rating_change.get("delta") is not None:
                        r["rating_change"] = rating_change["delta"]
                    if rating_change.get("newRating") is not None:
                        r["new_rating"] = rating_change["newRating"]

                stats = (statistics or {}).get(handle, {})
                problems = r.setdefault("problems", stats.get("problems", {}))

                for task, task_result in zip(tasks, row_data.get("tasks") or []):
                    short = task["letter"]
                    p = {}

                    if is_ioi:
                        score = task_result.get("score") or 0
                        if not score:
                            continue
                        p["result"] = score
                        max_score = task_result.get("maxScore") or task["maxScore"]
                        if max_score and 0 < score < max_score:
                            p["partial"] = True
                    else:
                        attempts = task_result.get("attempts") or 0
                        if task_result.get("solved"):
                            p["result"] = "+" if not attempts else f"+{attempts}"
                            if task_time := task_result.get("time"):
                                p["time"] = task_time
                        elif attempts:
                            p["result"] = f"-{attempts}"
                        else:
                            continue

                    if row_data.get("userId") is not None and first_ac_user_ids.get(short) == row_data["userId"]:
                        p["first_ac"] = True
                    problems.setdefault(short, {}).update(p)

                if not problems and not r["solving"]:
                    result.pop(handle)
        progress_bar.close()

        contest_problems = list(problems_infos.values())
        for problem in tqdm.tqdm(contest_problems, desc="problems fetching"):
            data = get_page_data(problem["url"], ignore_codes={403, 404})
            if data is None:
                continue
            code = (get_props(data, problem["url"]).get("task") or {}).get("number")
            if not code:
                continue
            problem["code"] = code
            archive_url = self.resource.problem_url.format(key=code)
            try:
                REQ.head(archive_url)
                problem["archive_url"] = archive_url
            except Exception:
                problem["archive_url"] = None

        problem_shorts = {p["name"]: p["short"] for p in contest_problems}
        problem_shorts.update({p["code"]: p["short"] for p in contest_problems if p.get("code")})
        submissions_info = self.contest.submissions_info
        attempts_url = self.url.rstrip("/") + "/attempts"

        for submission in process_submissions_url(attempts_url, submissions_info):
            task_name = submission.pop("task_name")
            task_id = submission.pop("task_id", None)
            handle = submission.pop("handle")
            upsolving = submission.pop("upsolving")

            short = problem_shorts.get(task_id) or problem_shorts.get(task_name)
            if short is None:
                continue

            created = handle not in result
            addition = result.setdefault(handle, {"member": handle, "_no_update_n_contests": True})
            if not process_submission_problem(submission, upsolving, short, addition) and created:
                result.pop(handle)

        ret = {
            "hidden_fields": ["affiliation"],
            "url": standings_url,
            "problems": contest_problems,
            "result": result,
            "submissions_info": submissions_info,
        }

        return ret

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):
        @RateLimiter(max_calls=5, period=1)
        def fetch_profile(handle):
            url = resource.profile_url.format(account=handle)
            try:
                data = get_page_data(url)
                if data is None:
                    raise ExceptionParseAccounts(f"Empty profile page for {handle}")
                props = get_props(data, url)
            except FailOnGetResponse as e:
                if e.code == 404:
                    return None
                raise e
            except (ExceptionParseStandings, json.JSONDecodeError) as e:
                raise ExceptionParseAccounts(f"Failed to parse profile page for {handle}") from e

            profile = props.get("profile")
            if not isinstance(profile, dict) or not profile.get("username"):
                raise ExceptionParseAccounts(f"Failed to parse profile page for {handle}")
            if profile["username"].lower() != handle.lower():
                raise ExceptionParseAccounts(f"Profile handle mismatch for {handle}: {profile['username']}")

            ret = {"name": profile.get("name")}
            if avatar := get_item(profile, "cosmetics.pic"):
                ret["avatar"] = urljoin(url, avatar)
            if title := get_item(props, "title.name"):
                ret["title"] = title

            stats = props.get("stats") or {}
            for field, key in (
                ("rating", "contestRating"),
                ("rank", "roboRank"),
                ("karma", "karma"),
                ("solved_tasks", "solvedTasks"),
                ("total_tasks", "totalTasks"),
            ):
                if stats.get(key) is not None:
                    ret[field] = stats[key]

            study = props.get("study") or {}
            for field, key in (
                ("study", "study"),
                ("study_level", "studyLevel"),
                ("region", "region"),
                ("district", "district"),
            ):
                if study.get(key):
                    ret[field] = study[key]

            return ret

        with PoolExecutor(max_workers=8) as executor:
            for data in executor.map(fetch_profile, users):
                if pbar:
                    pbar.update()
                if not data:
                    if data is None:
                        yield {"delete": True}
                    else:
                        yield {"skip": True}
                    continue

                yield {"info": data}

    @transaction.atomic()
    @staticmethod
    def update_submissions(account, resource, **kwargs):
        profile_url = resource.profile_url.format(account=account.key)
        attempts_url = profile_url.rstrip("/") + "/attempts"

        contests_cache = {}
        statistics_cache = {}
        updated_info = defaultdict(int)

        def get_contest(key, name):
            cache_key = (key, name)
            if cache_key in contests_cache:
                return contests_cache[cache_key]
            if key:
                contests = resource.contest_set.filter(problem_set__key=key)
            else:
                contests = resource.contest_set.filter(problem_set__name=name)
                account_statistics = account.statistics_set.filter(contest=OuterRef("pk"))
                contests = contests.annotate(has_stat=Exists(account_statistics))
                contests = contests.order_by("-has_stat", "start_time")
            contest = contests.first()
            contests_cache[cache_key] = contest
            return contest

        def get_statistic(contest):
            if contest not in statistics_cache:
                statistics_cache[contest], created = create_upsolving_statistic(
                    resource=resource, contest=contest, account=account
                )
            else:
                created = False
            return statistics_cache[contest], created

        for submission in process_submissions_url(attempts_url, account.submissions_info):
            task_name = submission.pop("task_name")
            task_id = submission.pop("task_id", None)
            submission.pop("handle")
            upsolving = submission.pop("upsolving")

            if not task_id and (not task_name or task_name == "—"):
                updated_info["missing_tasks"] += 1
                continue

            contest = get_contest(task_id, task_name)
            if contest is None:
                updated_info["missing_contests"] += 1
                continue

            for problem in contest.problems_list:
                if get_problem_name(problem) == task_name:
                    break
                if task_id and get_problem_key(problem) == task_id:
                    break
            else:
                updated_info["missing_problems"] += 1
                continue

            submission_time = arrow.get(submission["submission_time"]).datetime
            if account.last_submission is None or submission_time > account.last_submission:
                account.last_submission = submission_time

            short = get_problem_short(problem)
            statistic, created = get_statistic(contest)
            if process_submission_problem(submission, upsolving, short, statistic.addition):
                updated_info["n_updated"] += 1
                statistic.save()
            elif created:
                updated_info["n_removed_statistics"] += 1
                statistic.delete()
                statistics_cache.pop(contest)

        account.save(update_fields=["submissions_info", "last_submission"])
        return updated_info
