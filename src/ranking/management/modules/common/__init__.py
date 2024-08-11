#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import os
import urllib.parse
from abc import ABCMeta, abstractmethod
from copy import deepcopy
from datetime import datetime, timedelta

import pytz
from lazy_load import lz

from utils import parsed_table  # noqa
from utils.requester import FailOnGetResponse, ProxyLimitReached, requester  # noqa


def create_requester():
    req = requester(cookie_filename=os.path.join(os.path.dirname(__file__), 'cookies.txt'))
    req.caching = 'REQUESTER_CACHING' in os.environ
    req.time_out = 45
    req.debug_output = 'REQUESTER_DEBUG' in os.environ
    return req


REQ = lz(create_requester)

SPACE = ' '
DOT = '.'

UNCHANGED = '__unchanged__'

LOG = logging.getLogger('ranking.modules')


class BaseModule(object, metaclass=ABCMeta):
    def __init__(self, **kwargs):
        contest = kwargs.pop('contest', None)
        if contest is not None:
            kwargs.update(dict(
                contest=contest,
                pk=contest.pk,
                name=contest.title,
                url=contest.url,
                key=contest.key,
                standings_url=contest.standings_url,
                start_time=contest.start_time,
                end_time=contest.end_time,
                info=contest.info,
                resource=contest.resource,
                invisible=contest.invisible,
            ))
        for k, v in kwargs.items():
            setattr(self, k, v)

    @abstractmethod
    def get_standings(self, **kwargs):
        raise NotImplementedError()

    @staticmethod
    def get_users_infos(users, resource=None, accounts=None, pbar=None):
        raise NotImplementedError()

    @staticmethod
    def get_account_fields(account):
        resource = account.resource
        infos = resource.plugin.Statistic.get_users_infos(users=[account.key], resource=resource, accounts=[account])
        info = next(iter(infos)).get('info') or {}
        ret = {}
        for data in (info, info.pop('data_', None) or {}):
            for k, v in data.items():
                ret.setdefault(k, v)
        return ret

    @staticmethod
    def get_source_code(contest, problem):
        raise NotImplementedError()

    @staticmethod
    def get_rating_history(rating_data, stat, resource, date_from=None, date_to=None):
        raise NotImplementedError()

    @staticmethod
    def to_time(delta, num=3, short=False):
        if isinstance(delta, timedelta):
            delta = delta.total_seconds()
        delta = int(delta)

        if delta < 0:
            return '-' + BaseModule.to_time(-delta, num=num)

        a = []
        for _ in range(num - 1):
            a.append(delta % 60)
            delta //= 60
        a.append(delta)

        if short:
            while len(a) > 1 and a[-1] == 0:
                a.pop()
        return ':'.join(f'{x:02d}' if i else f'{x}' for i, x in enumerate(reversed(a)))

    @staticmethod
    def merge_dict(src, dst):
        if not dst:
            return src
        if isinstance(src, dict):
            ret = deepcopy(dst)
            ret.update({key: BaseModule.merge_dict(value, dst.get(key)) for key, value in src.items()})
            return ret
        if isinstance(src, (tuple, list)) and len(src) == len(dst):
            return [BaseModule.merge_dict(a, b) for a, b in zip(src, dst)]
        return src

    def get_season(self):
        year = self.start_time.year - (0 if self.start_time.month > 8 else 1)
        season = f'{year}-{year + 1}'
        return season

    def get_versus(self, *args, **kwargs):
        raise NotImplementedError()

    @staticmethod
    def get_upsolving_problems(statistics, handle):
        problems = {}
        if statistics and handle in statistics:
            for short, problem in statistics[handle].get('problems', {}).items():
                if 'upsolving' in problem:
                    problems[short] = {'upsolving': problem['upsolving']}
        return problems

    @property
    def host(self):
        urlinfo = urllib.parse.urlparse(self.url)
        return f'{urlinfo.scheme}://{urlinfo.netloc}/'

    @staticmethod
    def update_submissions(account, resource):
        raise NotImplementedError()

    @staticmethod
    def get_problem_info(problem, **kwargs):
        raise NotImplementedError()

    @staticmethod
    def get_new_problems(resource, **kwargs):
        raise NotImplementedError()


def save_proxy(req, filepath):
    if req.proxer.proxy:
        with open(filepath, 'w') as fo:
            json.dump(req.proxer.proxy, fo, indent=2)


def utc_now():
    return datetime.utcnow().replace(tzinfo=pytz.utc)


def main():
    with REQ:
        page = REQ.get('http://httpbin.org/get?env')
        print(page)
