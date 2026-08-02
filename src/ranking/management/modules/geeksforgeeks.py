#!/usr/bin/env python3

import json
import os
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

import dateutil.parser
from ratelimiter import RateLimiter

from ranking.management.modules import conf
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse


class Statistic(BaseModule):
    @staticmethod
    def _parse_app_profile(page):
        chunks = []
        regex = r"<script[^>]*>\s*self\.__next_f\.push\((?P<data>\[.*?\])\)\s*</script>"
        for match in re.finditer(regex, page, re.DOTALL):
            try:
                push_data = json.loads(match.group("data"))
            except json.JSONDecodeError:
                continue
            if (
                isinstance(push_data, list)
                and len(push_data) > 1
                and push_data[0] == 1
                and isinstance(push_data[1], str)
            ):
                chunks.append(push_data[1])

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
                    if value.get("username") and isinstance(value.get("articleCount"), dict):
                        return value
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)
        return None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        page = REQ.get("https://auth.geeksforgeeks.org/")
        form = REQ.form(page=page, action=None, fid="Login")
        if form:
            REQ.get("https://auth.geeksforgeeks.org/setLoginToken.php")
            page = REQ.submit_form(
                url="https://auth.geeksforgeeks.org/auth.php",
                data={
                    "user": conf.GEEKSFORGEEKS_USERNAME,
                    "pass": conf.GEEKSFORGEEKS_PASSWORD,
                },
                form=form,
            )

    def get_standings(self, users=None, statistics=None, **kwargs):
        result = {}

        @RateLimiter(max_calls=10, period=2)
        def fetch_and_process_page(page):
            url = f"https://practiceapi.geeksforgeeks.org/api/v1/contest/{self.key}/leaderboard/?page={page + 1}&type=current"  # noqa
            page = REQ.get(url)
            data = json.loads(page)

            for row in data["results"]["ranks_list"]:
                handle = row.pop("profile_link").rstrip("/").rsplit("/", 1)[-1]
                r = result.setdefault(handle, OrderedDict())
                name = row.pop("handle")
                if name != handle:
                    r["name"] = name
                r["member"] = handle
                r["place"] = row.pop("rank")
                r["solving"] = row.pop("score")
                last_correct_submission = row.get("last_correct_submission")
                if last_correct_submission:
                    time = dateutil.parser.parse(last_correct_submission + "+05:30")
                    delta = time - self.start_time
                    r["time"] = self.to_time(delta)
                for k, _ in list(row.items()):
                    if k.endswith("_score"):
                        r[k] = row.pop(k)

            return data

        try:
            data = fetch_and_process_page(0)
        except FailOnGetResponse as e:
            if e.code == 403:
                raise ExceptionParseStandings(str(e)) from e
            raise e
        total = data["results"]["rows_count"]
        per_page = len(data["results"]["ranks_list"])
        if not total or not per_page:
            raise ExceptionParseStandings("empty standings")
        n_pages = (total + per_page - 1) // per_page

        with PoolExecutor(max_workers=8) as executor:
            executor.map(fetch_and_process_page, range(1, n_pages))

        ret = {
            "url": os.path.join(self.url, "leaderboard"),
            "result": result,
        }
        return ret

    def get_users_infos(users, resource, accounts, pbar=None):
        @RateLimiter(max_calls=6, period=1)
        def fetch_profile(account):
            url = account.profile_url(resource)
            try:
                page = REQ.get(url)
            except FailOnGetResponse as e:
                if e.code == 404:
                    return None
                if e.code == 308 or e.code == 500:
                    return False
                raise e

            profile = Statistic._parse_app_profile(page)
            if profile is None:
                return False
            info = profile["articleCount"].copy()
            info["handle"] = profile["username"]

            if info["handle"] != account.key:
                return {"rename": info["handle"], "handle": account.key}

            return info

        with PoolExecutor(max_workers=4) as executor:
            profiles = executor.map(fetch_profile, accounts)
            for user, data in zip(users, profiles):
                if pbar:
                    pbar.update()

                if not data:
                    if data is None:
                        yield {"delete": True}
                    else:
                        yield {"skip": True}
                    continue

                assert user == data.pop("handle")

                if "rename" in data:
                    yield data
                    continue

                for k in list(data.keys()):
                    if isinstance(data[k], (dict, list, tuple)):
                        data.pop(k)

                yield {"info": data}
