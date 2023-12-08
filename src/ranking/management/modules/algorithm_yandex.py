# -*- coding: utf-8 -*-

import re

from ranking.management.modules import yandex


class Statistic(yandex.Statistic):

    def get_standings(self, *args, **kwargs):
        standings = super().get_standings(*args, **kwargs)

        if re.search(r'\bfinals?\b', self.name, re.I) and not re.search(r'\bsemi\b', self.name, re.I):
            if 'medals' not in standings.get('options', {}) and 'medals' not in self.info.get('standings', {}):
                options = standings.setdefault('options', {})
                options['medals'] = [{'name': name, 'count': 1} for name in ('gold', 'silver', 'bronze')]
        return standings
