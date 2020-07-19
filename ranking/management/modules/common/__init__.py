#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
from copy import deepcopy
from datetime import timedelta
from abc import ABCMeta, abstractmethod
import logging

from utils.requester import requester
from utils.requester import FailOnGetResponse  # noqa

REQ = requester(cookie_filename=os.path.join(os.path.dirname(__file__), 'cookies.txt'))
REQ.caching = 'REQUESTER_CACHING' in os.environ
REQ.time_out = 23
REQ.debug_output = 'REQUESTER_DEBUG' in os.environ

SPACE = ' '
DOT = '.'


ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)-10s - %(name)s - %(message)s',
                                  datefmt='%Y-%m-%d %H:%M:%S'))
ch.setLevel(logging.DEBUG)

LOG = logging.getLogger('ranking.modules')
LOG.setLevel(logging.INFO)
LOG.addHandler(ch)


class BaseModule(object, metaclass=ABCMeta):
    def __init__(self, **kwargs):
        contest = kwargs.pop('contest', None)
        if contest is not None:
            self.__init__(
                name=contest.title,
                url=contest.url,
                key=contest.key,
                standings_url=contest.standings_url,
                start_time=contest.start_time,
                end_time=contest.end_time,
                info=contest.info,
            )
        for k, v in kwargs.items():
            setattr(self, k, v)

    @abstractmethod
    def get_standings(self, users=None):
        pass

    @staticmethod
    def get_users_infos(users, resource=None, accounts=None, pbar=None):
        raise NotImplementedError()

    @staticmethod
    def get_source_code(contest, problem):
        raise NotImplementedError()

    @staticmethod
    def to_time(delta, num=None):
        if isinstance(delta, timedelta):
            delta = delta.total_seconds()
        delta = int(delta)

        if num == 2:
            return f'{delta // 60:02d}:{delta % 60:02d}'

        return f'{delta // 3600}:{delta // 60 % 60:02d}:{delta % 60:02d}'

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

    def get_result(self, *users):
        standings = self.get_standings(users)
        result = standings.get('result', {})
        return [result.get(u, None) for u in users]


def main():
    with REQ:
        page = REQ.get('http://httpbin.org/get?env')
        print(page)


if __name__ == "__main__":
    main()
