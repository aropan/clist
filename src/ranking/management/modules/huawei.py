#!/usr/bin/env python

from ranking.management.modules.common import BaseModule
from ranking.management.modules import open_kattis


class Statistic(BaseModule):

    def __new__(cls, **kwargs):
        contest = kwargs.get('contest')
        if contest:
            if 'kattis.com' in contest.url:
                return open_kattis.Statistic(**kwargs)
        return super().__new__(cls)
