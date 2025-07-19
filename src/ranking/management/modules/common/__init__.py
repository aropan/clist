#!/usr/bin/env python
# -*- coding: utf-8 -*-

import csv
import json
import logging
import os
import re
import urllib.parse
from abc import ABCMeta, abstractmethod
from copy import deepcopy
from datetime import datetime, timedelta

import pytz
from lazy_load import lz

from clist.templatetags.extras import as_number, get_item
from utils import parsed_table  # noqa
from utils.requester import requester


def create_requester():
    req = requester(
        cookie_filename=os.environ.get('REQUESTER_COOKIE_FILENAME', 'sharedfiles/cookies.txt'),
        proxy_filepath='sharedfiles/proxy',
    )
    req.caching = 'REQUESTER_CACHING' in os.environ
    req.time_out = 45
    req.debug_output = 'REQUESTER_DEBUG' in os.environ
    return req


REQ = lz(create_requester)


class CustomRequester:

    def __init__(self, req, *args, **kwargs):
        self._base_req = req
        self._args = args
        self._kwargs = kwargs

    def __call__(self, func):

        def wrapper(*args, **kwargs):
            with self._base_req(*self._args, **self._kwargs) as req:
                return func(*args, req=req, **kwargs)

        return wrapper


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
        for data in (info, info.pop('extra', None) or {}):
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
    def update_submissions(account, resource, **kwargs):
        raise NotImplementedError()

    @staticmethod
    def get_problem_info(problem, **kwargs):
        raise NotImplementedError()

    @staticmethod
    def get_archive_problems(resource, **kwargs):
        raise NotImplementedError()

    def complete_result(self, result):
        additions = self.info.get('additions')
        if additions:
            for row in result.values():
                if row['name'] in additions:
                    row.update(additions[row['name']])

        csv_data = get_item(self.info, 'standings._csv')
        if csv_data:
            csv_matching = csv_data['matching']
            addition_data = {}
            with open(csv_data['file'], 'r') as fo:
                rows = csv.reader(fo, **csv_data.get('fmtparams', {}))
                headers = next(rows)
                for row in rows:
                    row = dict(zip(headers, row))
                    if field_mapping := csv_data.get('field_mapping'):
                        field_types = csv_data.get('field_types', {})
                        updated_row = {}
                        for src, value in row.items():
                            if src not in field_mapping:
                                continue
                            dst = field_mapping[src]
                            path = dst.split('.')
                            if path[0] in ['place', 'problems', 'solving']:
                                value = as_number(value)
                            elif not value:
                                continue
                            o = updated_row
                            for k in path[:-1]:
                                o = o.setdefault(k, {})
                            k = path[-1]
                            field_type = field_types.get(dst)
                            if field_type == 'list':
                                o.setdefault(k, []).append(value)
                            else:
                                o[k] = value
                        row = updated_row
                    matching_value = row[csv_matching['csv_field']]
                    if 'csv_regex' in csv_matching:
                        matching_value = re.match(csv_matching['csv_regex'], matching_value).group(1)
                    addition_data[matching_value] = row

            for row in result.values():
                matching_value = row[csv_matching['result_field']]
                if 'result_regex' in csv_matching:
                    matching_value = re.match(csv_matching['result_regex'], matching_value).group(1)
                if matching_value in addition_data:
                    for k, v in addition_data[matching_value].items():
                        if not row.get(k):
                            row[k] = v


def save_proxy(req, filepath):
    if req.proxer.proxy:
        LOG.info(f'Saving proxy to {filepath}')
        with open(filepath, 'w') as fo:
            json.dump(req.proxer.proxy, fo, indent=2)


def utc_now():
    return datetime.utcnow().replace(tzinfo=pytz.utc)


def main():
    with REQ:
        page = REQ.get('http://httpbin.org/get?env')
        print(page)
