#!/usr/bin/env python
# -*- coding: utf-8 -*-

import bisect
import json
import os
import re
import zlib
from base64 import b64decode, b64encode
from collections import OrderedDict, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from functools import partial
from math import isclose
from pprint import pprint
from statistics import mean
from urllib.parse import urljoin

import pytz
from django.core.cache import cache
from django.utils import timezone
from django.utils.safestring import mark_safe
from flatten_dict import flatten
from prettytable import PrettyTable
from ratelimiter import RateLimiter

from clist.templatetags.extras import get_item, normalize_field
from logify import live as tqdm
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse, InitModuleException
from ranking.models import StatisticsLog
from utils.timetools import parse_datetime
from utils.tools import deep_iter


class Statistic(BaseModule):
    API_LEADERBOARD_URL = "/api/leaderboard?page={page}&round={round}"
    API_GAMES_URL = "/api/games?page={page}&limit={limit}&round={round}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        now = timezone.now()
        if self.start_time + timedelta(days=30) < now:
            raise InitModuleException("too old")
        self.round_name = get_item(self.info, "parse.name")
        if not self.round_name:
            raise InitModuleException("not found name")

    def get_standings(self, users=None, statistics=None, **kwargs):
        api_leaderboard_url = urljoin(self.host, self.API_LEADERBOARD_URL)
        page = 0
        total_pages = None
        result = {}
        place = 0
        hidden_fields = ["timestamp", "last_submitted_at", "advancement_status"]
        fields_types = {"timestamp": ["timestamp"], "last_submitted_at": ["timestamp"]}
        leaderboard_progress = tqdm.tqdm(total=1, desc="standings pages", unit="page")
        while (not total_pages and page == 0) or (total_pages and page < total_pages):
            page += 1
            url = api_leaderboard_url.format(page=page, round=self.round_name)
            data = REQ.get(url, return_json=True)
            total_pages = data["totalPages"]
            leaderboard_progress.total = max(total_pages, 1)
            for row in data["leaderboard"]:
                handle = row.pop("username")
                r = result.setdefault(handle, {})
                if avatar := row.pop("avatarFilename", None):
                    r["info"] = {"avatar": avatar}
                r["member"] = handle
                r["solving"] = row.pop("rating")
                place += 1
                r["place"] = place
                stat = (statistics or {}).get(handle, {})
                r["_last_five_upsolving_submissions"] = stat.get("_last_five_upsolving_submissions", [])
                for k, v in row.items():
                    k = normalize_field(k)
                    if k in fields_types and "timestamp" in fields_types[k]:
                        v = parse_datetime(v).timestamp()
                    if k not in r:
                        r[k] = v
            leaderboard_progress.update()
        leaderboard_progress.close()

        api_games_url = urljoin(self.host, self.API_GAMES_URL)

        @RateLimiter(max_calls=4, period=1)
        def fetch_games(page, limit):
            url = api_games_url.format(page=page, limit=limit, round=self.round_name)
            return REQ.get(url, return_json=True)

        data = fetch_games(1, 1)
        submissions_info = self.contest.submissions_info

        def fetch_new_games(limit, total_pages):
            last_upsolving_submission_id = submissions_info.pop("last_upsolving_submission_id", None)
            processed_games = set()
            new_games = []
            for page in tqdm.tqdm(range(1, total_pages + 1)):
                data = fetch_games(page, limit)
                games = []
                for game in data["games"]:
                    game["id"] = game.pop("_id")
                    for d in deep_iter(game):
                        if not isinstance(d, dict):
                            continue
                        d.pop("_id", None)
                        d.pop("storagePath", None)
                        for k, v in list(d.items()):
                            d.pop(k)
                            k = normalize_field(k)
                            d[k] = v
                        if "user" in d:
                            d["username"] = d.pop("user")["username"]
                    for k, v in list(game.items()):
                        if isinstance(v, dict):
                            game.pop(k)
                            game.update(v)
                    if "strategies" in game and isinstance(game["strategies"], list):
                        for strategy in game["strategies"]:
                            handle = strategy["username"]
                            if handle and handle in result:
                                strategy["round_rank"] = result[handle]["place"]
                    games.append(game)

                n_processed_games = 0
                stop = False
                for game in games:
                    if last_upsolving_submission_id and last_upsolving_submission_id == game["id"]:
                        stop = True
                        break
                    n_processed_games += 1
                    if game["id"] in processed_games:
                        continue
                    processed_games.add(game["id"])
                    game["time"] = parse_datetime(game["created_at"]).timestamp()
                    if game["status"] in ["in_progress", "pending"]:
                        submissions_info.pop("last_upsolving_submission_id", None)
                        submissions_info.pop("last_upsolving_submission_time", None)
                    elif "last_upsolving_submission_id" not in submissions_info:
                        submissions_info["last_upsolving_submission_id"] = game["id"]
                        submissions_info["last_upsolving_submission_time"] = game["time"]
                    if not game.get("player_results"):
                        continue
                    game["type"] = StatisticsLog.LogType.GAME
                    new_games.append(game)
                if stop:
                    break
            if "last_upsolving_submission_id" not in submissions_info and last_upsolving_submission_id:
                submissions_info["last_upsolving_submission_id"] = last_upsolving_submission_id
            new_games = list(reversed(new_games))
            return new_games

        def collect_upsolving_submissions(new_games):
            processed_games = defaultdict(set)
            for r in result.values():
                for game in r["_last_five_upsolving_submissions"]:
                    processed_games[r["member"]].add(game["id"])
            for game in new_games:
                for strategy in game["strategies"]:
                    handle = strategy["username"]
                    if handle not in result:
                        continue
                    if game["id"] in processed_games[handle]:
                        continue
                    processed_games[handle].add(game["id"])

                    r = result[handle]

                    last_five = r["_last_five_upsolving_submissions"]
                    last_five.append(game)
                    if len(last_five) > 5:
                        last_five.pop(0)

                    upsolving_submissions = r.setdefault("upsolving_submissions", [])
                    upsolving_submissions.append({"contest": self.contest, "info": game.copy(), "problem": None})

        limit = 20
        total_games = data["totalGames"]
        total_pages = (total_games + limit - 1) // limit
        new_games = fetch_new_games(limit, total_pages)
        collect_upsolving_submissions(new_games)

        return {
            "result": result,
            "hidden_fields": hidden_fields,
            "fields_types": fields_types,
            "submissions_info": submissions_info,
            "info_fields": ["_has_versus"],
            "_has_versus": {"enable": bool(submissions_info)},
        }

    @staticmethod
    def _ordered_players(game):
        players = [{**strategy, **result} for strategy, result in zip(game["strategies"], game["player_results"])]
        players = list(sorted(players, key=lambda x: x["rank"]))
        for player in players:
            x = player["rating_change"]
            player["rating_change"] = ("+" if x > 0 else ("±" if x == 0 else "")) + str(x)
        return players

    def get_versus(self, statistic):
        stats = defaultdict(lambda: defaultdict(int))
        my_handle = statistic.account.key
        my_stat = stats[my_handle]
        statistics_logs = list(statistic.statisticslog_set.order_by("-time"))
        for game_idx, statistic_log in enumerate(statistics_logs):
            game = statistic_log.data
            if game["status"] != "completed":
                continue
            players = self._ordered_players(game)
            for my_player in players:
                if my_player["username"] != my_handle:
                    continue
                for op_player in players:
                    if op_player["username"] == my_handle:
                        continue
                    delta = my_player["rank"] - op_player["rank"]
                    result = "draw" if delta == 0 else ("win" if delta < 0 else "lose")

                    op_stat = stats[op_player["username"]]
                    my_stat["total"] += 1
                    op_stat["total"] += 1
                    my_stat[result] += 1
                    op_stat[result] += 1

                    game_info = {
                        **game,
                        "index": len(statistics_logs) - game_idx,
                        "url": self.resource.href() + f"/games/{game['id']}/replay",
                        "players": players,
                        "result": result,
                    }
                    my_stat.setdefault("games", []).append(game_info)
                    op_stat.setdefault("games", []).append(game_info)

        results = {
            "stats": stats,
            "games": {"fields": ["index"] + ["url", "id", "preset", "rank", "username", "score", "rating_change"]},
        }
        return True, results

    @staticmethod
    def compose_message_by_game(resource, contest, game):
        url = resource.href() + f"games/{game['id']}/replay"
        lines = []
        lines += [f"Contest: [{contest.title}]({contest.actual_url})"]
        lines += [f"Game ID: [{game['id']}]({url})"]
        lines += [f"Created: *{game['created_at']}*"]
        lines += [f"Preset: *{game['preset']}*"]
        players = Statistic._ordered_players(game)
        mapping = {"round_rank": "rank", "username": "user", "version": "ver", "rating_change": "rating"}
        fields = ["round_rank", "username", "version", "score", "rating_change"]
        field_names = [mapping.get(f, f) for f in fields]
        table = PrettyTable(field_names=field_names, border=False)
        for player in players:
            table.add_row([str(player.get(field, "-")) for field in fields])
        lines += [f"```{table.get_string()}```"]
        return "\n".join(lines)
