# -*- coding: utf-8 -*-

from urllib.parse import urlparse

from ranking.management.modules import opencup, yandex
from ranking.management.modules.common import BaseModule


class Statistic(BaseModule):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        host = urlparse(self.standings_url).netloc

        year = self.start_time.year - (0 if self.start_time.month > 9 else 1)
        season = f'{year}-{year + 1}'
        kwargs.setdefault('season', season)

        if not host or 'yandex' in host:
            self.module = yandex.Statistic(**kwargs)
        else:
            self.module = opencup.Statistic(**kwargs)

    def get_standings(self, **kwargs):
        return self.module.get_standings(**kwargs)
