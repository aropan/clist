# -*- coding: utf-8 -*-

import re

from ranking.management.modules import solve, yandex
from ranking.management.modules.common import BaseModule
from ranking.management.modules.excepts import InitModuleException


class Statistic(BaseModule):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.standings_url:
            raise InitModuleException('No standings url')
        if 'yandex' in self.standings_url:
            self._module = yandex.Statistic(*args, **kwargs)
        elif self.key.startswith('solve:'):
            kwargs['prefix_handle'] = 'solve:'
            self._module = solve.Statistic(*args, **kwargs)
        else:
            raise InitModuleException(f'No support standings url = {self.standings_url}')

    def get_standings(self, users=None, statistics=None):
        standings = self._module.get_standings(users, statistics)
        is_final = re.search(r'\bfinal\b', self.name, re.IGNORECASE)
        if is_final:
            options = standings.setdefault('options', {})
            medals = [{'name': medal, 'count': 1} for medal in ('gold', 'silver', 'bronze')]
            options['medals'] = medals
            standings['series'] = 'bsuir-open'
        return standings
