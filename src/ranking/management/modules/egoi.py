#!/usr/bin/env python

import html
import json
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import urljoin

from first import first
from multiset import Multiset
from pprint import pprint

from clist.templatetags.extras import as_number
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    def get_standings(self, users=None, statistics=None, **kwargs):
        result = {}
        season = self.get_season()
        if not self.standings_url:
            raise ExceptionParseStandings("Empty standings_url")
        standings_page = REQ.get(self.standings_url)
        match = re.search(r'url:\s*"(?P<path>[^"]*)"', standings_page)
        url = urljoin(self.standings_url, match.group("path"))
        standings_data = REQ.get(url)

        lines = iter(standings_data.strip().splitlines())
        _ = next(lines)  # skip now and duration
        n_problems = int(next(lines))
        problems_infos = {}
        for idx in range(n_problems):
            parts = next(lines).split()
            problem_info = {"short": chr(ord("A") + idx)}
            problem_id, *parts = parts
            if parts:
                problem_info["name"], *parts = parts
            if parts:
                n = int(parts.pop(0))
                problem_info["subscores"] = list(map(int, parts[:n]))
                parts = parts[n:]
            problems_infos[problem_id] = problem_info
        n_contestants = int(next(lines))
        for idx in range(n_contestants):
            name = next(lines)
            member = f"{name} {season}"
            row = {"member": member, "name": name}
            row["country"] = next(lines)
            n_submissions = int(next(lines))
            problems = row.setdefault("problems", {})
            submissions = []
            for _ in range(n_submissions):
                parts = next(lines).split()
                problem_id, *parts = parts
                time = int(parts.pop(0))
                if not parts or parts[0] == "?":
                    continue
                subscores = list(map(int, parts))
                submissions.append({"problem_id": problem_id, "time": time, "subscores": subscores})
            submissions.sort(key=lambda s: s["time"])
            for submission in submissions:
                problem_id = submission["problem_id"]
                time = submission["time"]
                subscores = submission["subscores"]
                problem_info = problems_infos[problem_id]
                problem = problems.setdefault(problem_info["short"], {})
                problem_subtasks = problem.setdefault("subtasks", [])
                while len(problem_subtasks) < len(subscores):
                    problem_subtasks.append({})
                for idx, subscore in enumerate(subscores):
                    subtask = problem_subtasks[idx]
                    if "score" not in subtask or subtask["score"] < subscore:
                        subtask["time"] = time
                        subtask["score"] = subscore
                        problem["time"] = self.to_time(time, 3)
                    subtask["partial"] = subtask["score"] < problem_info["subscores"][idx]
                problem["result"] = sum(sub["score"] for sub in problem_subtasks)
                problem["partial"] = any(sub["partial"] for sub in problem_subtasks)
            row["solving"] = sum(problem["result"] for problem in problems.values())
            result[member] = row

        last_rank = None
        last_score = None
        for rank, row in enumerate(sorted(result.values(), key=lambda x: x["solving"], reverse=True), start=1):
            if row["solving"] != last_score:
                last_rank = rank
                last_score = row["solving"]
            row["place"] = last_rank

        standings = {
            "result": result,
            "url": self.standings_url,
            "problems": list(problems_infos.values()),
            "series": "egoi",
        }

        return standings
