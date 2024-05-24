#!/usr/bin/env python

from urllib.parse import urlparse

from ranking.management.modules import open_kattis
from ranking.management.modules.common import BaseModule


class Statistic(BaseModule):

    def __new__(cls, **kwargs):
        contest = kwargs.get('contest')
        if contest:
            if urlparse(contest.url).netloc.endswith('.kattis.com'):
                return open_kattis.Statistic(**kwargs)
        return super().__new__(cls)
