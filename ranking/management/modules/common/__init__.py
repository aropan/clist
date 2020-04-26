#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
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
    def get_users_infos(users, pbar):
        raise NotImplementedError()

    @staticmethod
    def to_time(delta):
        if isinstance(delta, timedelta):
            delta = delta.total_seconds()
        delta = int(delta)
        return f'{delta // 3600}:{delta // 60 % 60:02d}:{delta % 60:02d}'

    @staticmethod
    def merge_dict(src, dst):
        for key, value in src.items():
            if isinstance(value, dict):
                node = dst.setdefault(key, {})
                BaseModule.merge_dict(value, node)
            else:
                dst[key] = value
        return dst

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
