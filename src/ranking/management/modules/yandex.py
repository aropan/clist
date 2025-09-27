# -*- coding: utf-8 -*-

import html
import os
import random
import re
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from copy import deepcopy
from datetime import timedelta
from urllib.parse import urljoin

import tqdm
from django.utils import timezone
from ipwhois import IPWhois
from ratelimiter import RateLimiter

from clist.templatetags.extras import as_number, get_item, is_improved_solution
from my_oauth.models import Service
from ranking.management.modules.common import LOG, REQ, BaseModule, parsed_table
from ranking.management.modules.common.locator import Locator
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse
from utils.mathutils import max_with_none
from utils.timetools import parse_datetime


def normalize_standings_url(url):
    if not url:
        return
    url = re.sub("enter/?", "", url)
    url = re.sub(r"\?.*$", "", url)
    url = re.sub("/?$", "", url)
    if not url.endswith("/standings"):
        url = os.path.join(url, "standings")
    return url


class Statistic(BaseModule):
    YANDEX_API_URL = "https://api.contest.yandex.net/api/public/v2"
    SUBMISSION_FIELDS_MAPPING = {
        "submission_id": "runId",
        "verdict_full": "verdict",
        "verdict": lambda submission: "".join(filter(str.isupper, submission["verdict"])),
        "max_memory_usage": "maxMemoryUsage",
        "max_time_usage": "maxTimeUsage",
        "time_in_seconds": lambda submission: submission["timeFromStart"] / 1000,
        "language": "compiler",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.standings_url:
            self.standings_url = normalize_standings_url(self.url)

    def _get_headers(self) -> dict | None:
        coder_pk = get_item(self.resource.info, "statistics.competitive_hustle_coder_pk")
        if not coder_pk:
            return

        ouath_service = Service.objects.get(name="yandex-contest")
        oauth_token = ouath_service.token_set.filter(coder__pk=coder_pk).first()
        if not oauth_token:
            return

        access_token = oauth_token.get_access_token()
        headers = {"Authorization": f"OAuth {access_token}"}
        return headers

    def _get_all_submissions(self, contest_id):
        if not contest_id:
            return
        headers = self._get_headers()
        if not headers:
            return

        page = 0
        size = 10000
        total = None
        n_submissions = 0
        while total is None or page * size < total:
            page += 1
            url = f"{Statistic.YANDEX_API_URL}/contests/{contest_id}/submissions?page={page}&pageSize={size}"
            try:
                data = REQ.get(url, headers=headers, return_json=True)
            except FailOnGetResponse as e:
                LOG.warning(f"Fail to get submission ids: {e}")
                break
            for submission in data["submissions"]:
                n_submissions += 1
                yield submission
            total = data["count"]
        LOG.info(f"{n_submissions} submissions fetched from {contest_id} contest")

    def _get_submission_infos(self, names_result):
        already_processed = set()
        submission_infos = {}
        max_run_id = self.contest.variables.get("max_run_id")
        for row in names_result.values():
            name = row.get("name")
            problems = row.get("problems")
            if not name or not problems:
                continue

            for short, problem in problems.items():
                if not problem.get("_submission_infos"):
                    continue
                row_problems = submission_infos.setdefault(name, {})
                _submission_infos = problem["_submission_infos"]
                if max_run_id:
                    _submission_infos = [info for info in _submission_infos if info["run_id"] <= max_run_id]
                row_problems[short] = {"_submission_infos": _submission_infos}
                for submission_info in _submission_infos:
                    already_processed.add(submission_info["run_id"])

        headers = self._get_headers()
        submissions = list(self._get_all_submissions(self.key))
        if not headers or not submissions:
            return submission_infos, None

        run_ids = [s["id"] for s in submissions if s["author"] in names_result]
        run_ids = [run_id for run_id in run_ids if run_id not in already_processed]
        if max_run_id:
            run_ids = [run_id for run_id in run_ids if run_id <= max_run_id]
        random.shuffle(run_ids)

        LOG.info(f"{len(run_ids)} submissions to fetch, already {len(already_processed)}, total {len(submissions)}")

        stop_fetch_submissions = False
        finish_time = timezone.now() + timedelta(minutes=10)
        rate_limiter = RateLimiter(max_calls=4, period=1)
        n_success = 0
        n_fail = 0
        success_rate = 1
        success_rate_alpha = 0.1

        def fetch_submissions(page):
            nonlocal stop_fetch_submissions, n_success, n_fail, success_rate
            if stop_fetch_submissions:
                return
            if timezone.now() > finish_time:
                LOG.warning("Fetch submissions timeout")
                stop_fetch_submissions = True
                return
            with rate_limiter:
                offset = batch_size * page
                run_ids_query = "&".join(f"runIds={run_id}" for run_id in run_ids[offset:offset + batch_size])
                url = f"{Statistic.YANDEX_API_URL}/contests/{self.key}/submissions/multiple?{run_ids_query}"
                try:
                    submissions = REQ.get(url, headers=headers, return_json=True)
                    n_success += 1
                    return submissions
                except FailOnGetResponse as e:
                    n_fail += 1
                    n_total = n_success + n_fail
                    success_rate += (n_success / n_total - success_rate) * success_rate_alpha
                    LOG.warning(f"Fail to get submission infos: {e}, url = {url}, success rate = {success_rate:.2%}")
                    if n_total >= 10 and success_rate < 0.3:
                        stop_fetch_submissions = True

        run_ids = list(set(run_ids))
        batch_size = 10
        n_page = (len(run_ids) - 1) // batch_size + 1
        n_processed = len(already_processed)
        n_total = len(run_ids) + n_processed
        with (
            PoolExecutor(max_workers=8) as executor,
            tqdm.tqdm(total=n_page, desc="fetch submissions") as pbar,
        ):
            for submissions in executor.map(fetch_submissions, range(n_page)):
                pbar.update()
                if submissions is None:
                    continue
                for submission in submissions:
                    submission_time = parse_datetime(submission["submissionTime"])
                    upsolving = submission_time > self.end_time
                    n_processed += 1
                    name = submission["participantInfo"]["name"]
                    short = submission["problemAlias"]
                    final_score = submission.get("finalScore")
                    submission_problem = submission_infos.setdefault(name, {}).setdefault(short, {})
                    problem = get_item(names_result[name], ("problems", short))
                    if upsolving:
                        if problem is not None:
                            problem = problem.setdefault("upsolving", {})
                        else:
                            submission_problem = submission_problem.setdefault("upsolving", {})
                    if (
                        not problem
                        or as_number(final_score) == as_number(problem.get("result"))
                        and ("submission_id" not in problem or submission["runId"] < problem["submission_id"])
                    ):
                        fields_data = problem or submission_problem
                        for (
                            field,
                            source,
                        ) in Statistic.SUBMISSION_FIELDS_MAPPING.items():
                            if callable(source):
                                value = source(submission)
                            else:
                                value = submission[source]
                            fields_data[field] = value

                    submission_info = {
                        "ip": submission["ip"],
                        "run_id": submission["runId"],
                    }
                    submission_infos[name][short].setdefault("_submission_infos", []).append(submission_info)

        submissions_percentage = 100 * n_processed // n_total if n_total else False
        return submission_infos, submissions_percentage

    def _get_upsolving_submissions(self, contest, problems_info, names_result):
        submissions_info = self.contest.submissions_info
        last_upsolving_submission_time = parse_datetime(submissions_info.get("last_upsolving_submission_time"))
        last_upsolving_submission_id = submissions_info.get("last_upsolving_submission_id")
        max_submission_time = last_upsolving_submission_time
        max_submission_id = last_upsolving_submission_id
        counters = defaultdict(int)

        for contest_key, contest_url in (
            (contest.upsolving_key, contest.upsolving_url),
            (contest.key, contest.standings_url),
        ):
            if counters:
                break
            if contest_url:
                contest_url = re.sub("standings/?", "", contest_url)
            for submission in self._get_all_submissions(contest_key):
                submission_id = submission["id"]
                submission_time = parse_datetime(submission["submissionTime"])

                max_submission_id = max_with_none(max_submission_id, submission_id)
                max_submission_time = max_with_none(max_submission_time, submission_time)

                if last_upsolving_submission_time and submission_time <= last_upsolving_submission_time:
                    counters["n_time_skipped"] += 1
                    continue
                if last_upsolving_submission_id and submission_id <= last_upsolving_submission_id:
                    counters["n_id_skipped"] += 1
                    continue

                name = submission["author"]
                if name not in names_result:
                    counters["n_missed_name"] += 1
                    continue
                if submission_time < contest.end_time:
                    counters["n_contest_skipped"] += 1
                    continue
                short = submission["problemAlias"]
                if short not in problems_info:
                    counters["n_missed_problem"] += 1
                    continue
                row = names_result[name]

                submission_result = submission["score"]
                submission_info = {
                    "submission_id": submission_id,
                    "submission_time": submission_time.timestamp(),
                    "verdict_full": submission["verdict"],
                    "verdict": "".join(filter(str.isupper, submission["verdict"])),
                    "max_memory_usage": submission["memory"],
                    "max_time_usage": submission["time"],
                    "time_in_seconds": submission["timeFromStart"] / 1000,
                    "language": submission["compiler"],
                    "test": submission["test"],
                }

                problem = get_item(row, ("problems", short, "upsolving"))
                submission_result_value = as_number(submission_result, default=0)
                problem_result_value = as_number(problem and problem.get("result"), default=0)
                if (
                    problem
                    and submission_result_value >= problem_result_value
                    and (
                        "submission_time" not in problem
                        or submission_info["submission_time"] < problem["submission_time"]
                    )
                ):
                    counters["n_updated"] += 1
                    problem.update(submission_info)
                    if "result" not in problem or submission_result_value > problem_result_value:
                        problem["result"] = submission_result_value

                submission_info["result"] = submission_result
                problem_info = deepcopy(problems_info[short])
                if contest_url:
                    problem_info["url"] = urljoin(contest_url, f"problems/{short}")
                row.setdefault("upsolving_submissions", []).append(
                    {
                        "contest": contest,
                        "problem": problem_info,
                        "info": submission_info,
                    }
                )
                row["_last_submission"] = max_with_none(row.get("_last_submission"), submission_time)
                counters["n_upsolving"] += 1
        if max_submission_time:
            submissions_info["last_upsolving_submission_time"] = max_submission_time.isoformat()
        if max_submission_id:
            submissions_info["last_upsolving_submission_id"] = max_submission_id

        sorted_counters = dict(sorted(counters.items(), key=lambda x: x[1], reverse=True))
        LOG.info(f"Upsolving submissions: {sorted_counters}")
        return sorted_counters

    def _get_account_renaming(self, contset_ids):
        headers = self._get_headers()
        if not headers:
            return {}

        name2logins = defaultdict(list)
        login2name = {}
        for contest_id in contset_ids:
            if not contest_id:
                continue

            try:
                page = 1
                page_size = 1000
                while True:
                    url = f"{Statistic.YANDEX_API_URL}/contests/{contest_id}/standings?page={page}&pageSize={page_size}"
                    standings_data = REQ.get(url, headers=headers, return_json=True)
                    processed_participant_ids = set()
                    participant_names = set()
                    n_rows = 0
                    for standings_row in standings_data["rows"]:
                        participant = standings_row["participantInfo"]
                        if participant["id"] in processed_participant_ids:
                            continue
                        processed_participant_ids.add(participant["id"])
                        n_rows += 1
                        name = participant["name"]
                        if name not in participant_names:
                            participant_names.add(name)
                        if login := participant.get("login"):
                            if login not in name2logins[name]:
                                name2logins[name].append(login)
                            login2name[login] = name
                    if n_rows < page_size:
                        break
                    page += 1
                url = f"{Statistic.YANDEX_API_URL}/contests/{contest_id}/participants"
                data = REQ.get(url, headers=headers, return_json=True)
            except FailOnGetResponse:
                continue
            for participant in data:
                name = participant["name"]
                if name in participant_names:
                    continue
                if login := participant.get("login"):
                    if login not in name2logins[name]:
                        name2logins[name].append(login)
                    login2name[login] = name
        LOG.info(f"Found {len(name2logins)} participant names and {len(login2name)} participant logins")
        return name2logins

    def get_standings(self, users=None, statistics=None, **kwargs):
        if not hasattr(self, "season"):
            year = self.start_time.year - (0 if self.start_time.month > 8 else 1)
            season = f"{year}-{year + 1}"
        else:
            season = self.season

        result = {}
        problems_info = OrderedDict()

        if not re.search("/[0-9]+/", self.standings_url):
            return {}

        name2logins = self._get_account_renaming([self.contest.key, self.contest.upsolving_key])

        for url, upsolving in (
            (self.standings_url, False),
            (normalize_standings_url(self.contest.upsolving_url), True),
        ):
            if not url:
                continue

            tqdm_pagination = None
            n_page = 1
            while True:
                page = REQ.get(url)

                if n_page == 1:
                    pages = re.findall('<a[^>]*href="[^"]*standings[^"]*p[^"]*=([0-9]+)"[^>]*>', page)
                    if pages:
                        max_page = max(map(int, pages))
                        tqdm_pagination = tqdm.tqdm(total=max_page, desc="fetch standings pages")

                match = re.search(
                    '<table[^>]*class="[^"]*standings[^>]*>.*?</table>',
                    page,
                    re.MULTILINE | re.DOTALL,
                )
                if not match:
                    raise ExceptionParseStandings("Not found table standings")

                html_table = match.group(0)
                unnamed_fields = self.info.get("standings", {}).get("unnamed_fields", [])
                table = parsed_table.ParsedTable(html_table, unnamed_fields=unnamed_fields)

                for r in table:
                    row = {}
                    problems = row.setdefault("problems", {})
                    solved = 0
                    has_solved = False
                    for k, v in list(r.items()):
                        if "table__cell_role_result" in v.attrs["class"]:
                            letter = k.split(" ", 1)[0]
                            if letter == "X":
                                continue
                            if not upsolving:
                                p = problems_info.setdefault(letter, {"short": letter})
                                names = v.header.node.xpath(".//span/@title")
                                if len(names) == 1:
                                    name = html.unescape(names[0])
                                    sample = re.search(r"\((?P<full>[0-9]+)\s*балл.{,3}\)$", name, re.I)
                                    if sample:
                                        st, _ = sample.span()
                                        name = name[:st].strip()
                                        p["full_score"] = int(sample.group("full"))
                                    p["name"] = name

                            p = problems.setdefault(letter, {})
                            if upsolving:
                                p = p.setdefault("upsolving", {})
                            n = v.column.node
                            if n.xpath('img[contains(@class,"image_type_success")]'):
                                res = "+"
                                p["binary"] = True
                            elif n.xpath('img[contains(@class,"image_type_fail")]'):
                                res = "-"
                                p["binary"] = False
                            else:
                                res = v.value.split(" ", 1)[0]
                                res = res.replace(",", "")
                                res = res.replace("—", "-")
                                if not res.startswith("?") and res != "+" and as_number(res, force=True) is None:
                                    problems.pop(letter)
                                    continue
                            p["result"] = res
                            if " " in v.value:
                                p["time"] = v.value.split(" ", 1)[-1]
                            if "table__cell_firstSolved_true" in v.attrs["class"]:
                                p["first_ac"] = True
                            if "+" in res or res.startswith("100"):
                                solved += 1
                            try:
                                has_solved = has_solved or "+" not in res and float(res) > 0
                            except ValueError:
                                pass
                        elif "table__cell_role_participant" in v.attrs["class"]:
                            title = v.column.node.xpath(".//@title")
                            if title:
                                name = str(title[0])
                            else:
                                name = v.value.replace(" ", "", 1)
                            row["name"] = name
                            row["member"] = name if " " not in name else f"{name} {season}"

                            country = v.column.node.xpath(".//div[contains(@class,'country-flag')]/@title")
                            if country:
                                row["country"] = str(country[0])

                        elif "table__cell_role_place" in v.attrs["class"]:
                            row["place"] = v.value
                        elif "table__header_type_penalty" in v.attrs["class"]:
                            row["penalty"] = int(v.value) if re.match("^-?[0-9]+$", v.value) else v.value
                        elif "table__header_type_score" in v.attrs["class"]:
                            row["solving"] = as_number(v.value.replace(",", ""))
                    if has_solved:
                        row["solved"] = {"solving": solved}
                    if not problems:
                        continue

                    member = row["member"]

                    def set_member(new_member):
                        nonlocal member
                        if member == new_member:
                            return
                        if statistics and member in statistics:
                            statistics[new_member] = statistics.pop(member)
                            row["previous_member"] = member
                        member = new_member
                        row["member"] = member

                    if name2logins:
                        name = row["name"]
                        if name not in name2logins:
                            raise ExceptionParseStandings(f"Not found {name} in name2logins")
                        logins = name2logins[name]
                        row["_logins"] = logins
                        for login in logins:
                            if member in result:
                                break
                            set_member(login)
                            if "previous_member" in row:
                                break
                    elif self.resource.has_standings_renamed_account and (
                        renaming := self.resource.accountrenaming_set.filter(old_key=member).first()
                    ):
                        set_member(renaming.new_key)

                    statistics_problems = get_item(statistics, (member, "problems"), {})

                    if upsolving:
                        if member not in result:
                            for field in "place", "penalty", "solving":
                                row.pop(field, None)
                            row["_no_update_n_contests"] = True
                            result[member] = row
                        else:
                            result_problems = result[member]["problems"]
                            for short, problem in problems.items():
                                p = result_problems.setdefault(short, {})
                                if is_improved_solution(problem["upsolving"], p):
                                    p["upsolving"] = problem["upsolving"]

                        if self.contest.submissions_info and statistics_problems:
                            for short, problem in problems.items():
                                if not (upsolving := get_item(problem, "upsolving")):
                                    continue
                                if not (old_upsolving := get_item(statistics_problems, (short, "upsolving"))):
                                    continue
                                if as_number(upsolving["result"]) != as_number(old_upsolving["result"]):
                                    continue
                                upsolving.update(old_upsolving)
                        continue

                    for short in statistics_problems:
                        problems.setdefault(short, {})
                    for short, problem in problems.items():
                        if short not in statistics_problems:
                            continue
                        statistics_problem = statistics_problems[short]
                        for key, value in statistics_problem.items():
                            if key in Statistic.SUBMISSION_FIELDS_MAPPING and key not in problem:
                                problem[key] = value
                        if "_submission_infos" in statistics_problem:
                            problem["_submission_infos"] = statistics_problem["_submission_infos"]
                        if "upsolving" in statistics_problem:
                            problem["upsolving"] = statistics_problem["upsolving"]
                    result[member] = row
                if tqdm_pagination:
                    tqdm_pagination.update()
                n_page += 1
                match = re.search(
                    f'<a[^>]*href="(?P<href>[^"]*standings[^"]*p[^"]*={n_page})"[^>]*>',
                    page,
                )
                if not match:
                    break
                url = urljoin(url, match.group("href"))
            if tqdm_pagination:
                tqdm_pagination.close()

        hidden_fields = set(Locator.location_fields)
        default_locations = get_item(self.resource, "info.standings.default_locations")
        with Locator(default_locations=default_locations) as locator:
            for row in tqdm.tqdm(result.values(), desc="fetch locations"):
                if "country" in row:
                    continue
                name = row["name"]
                match = re.search(r",\s*(?P<address>[^,]+)$", name)
                if not match:
                    continue
                address = match.group("address")
                location = locator.get_location_dict(address, lang="ru")
                if not location:
                    continue
                row.update(location)

        names_result = {row["name"]: row for row in result.values()}
        submission_infos, submissions_percentage = self._get_submission_infos(names_result) or {}
        whois = self.info.setdefault("_whois", {})
        contest_ips = set()
        contest_n_ips = set()
        contest_whois = defaultdict(set)

        for row in result.values():
            name = row["name"]
            if name not in submission_infos:
                continue
            problems = row["problems"]
            ips = set()
            for short, problem_data in submission_infos[name].items():
                problems.setdefault(short, {}).update(problem_data)
                ips |= {info["ip"] for info in problem_data.get("_submission_infos", [])}
            contest_ips |= ips
            row["_ips"] = list(sorted(ips))
            contest_n_ips |= {len(ips)}
            row["_n_ips"] = len(ips)

            for ip in row["_ips"]:
                if ip not in whois:
                    lookup = IPWhois(ip).lookup_whois()
                    nets = lookup.get("nets")
                    if not nets:
                        continue
                    net = nets[0]
                    description = net.get("description")
                    if description:
                        description = re.sub(r"\n\s*", "; ", description)
                    whois[ip] = {
                        "name": net.get("name"),
                        "range": net.get("range"),
                        "description": description,
                        "country": net.get("country"),
                    }
                for field, value in whois[ip].items():
                    if value:
                        key = f"_whois_{field}"
                        row_values = row.setdefault(key, [])
                        row_values.append(value)
                        contest_whois[key].add(value)

        upsolving_counters = self._get_upsolving_submissions(self.contest, problems_info, names_result)

        standings = {
            "result": result,
            "url": self.standings_url,
            "problems": list(problems_info.values()),
            "hidden_fields": list(hidden_fields),
            "parsed_percentage": submissions_percentage,
            "submissions_info": self.contest.submissions_info,
        }

        if upsolving_counters:
            counters = standings.setdefault("counters", {})
            counters["upsolving"] = upsolving_counters

        if contest_ips:
            info_fields = standings.setdefault("info_fields", [])
            info_fields.extend(["_ips", "_n_ips", "_whois"])
            standings["_ips"] = list(sorted(contest_ips))
            standings["_n_ips"] = list(sorted(contest_n_ips))
            standings["_whois"] = whois
            for field, values in contest_whois.items():
                info_fields.append(field)
                standings[field] = list(sorted(values))

        now = timezone.now()
        if now < self.end_time < now + timedelta(hours=2):
            if submissions_percentage and submissions_percentage < 100:
                standings["timing_statistic_delta"] = timedelta(minutes=1)

        return standings
