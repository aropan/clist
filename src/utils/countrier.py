#!/usr/bin/env python3

from logging import getLogger
from collections import defaultdict

from django.utils.translation import override
from django_countries import countries


class Countrier:

    def __init__(self):
        self.countries_name = {name.lower(): code for code, name in countries}
        with override('ru'):
            self.countries_name.update({name.lower(): code for code, name in countries})
        self.countries_name.update({code.lower(): code for code, name in countries})
        self.countries_name.update({countries.alpha3(code).lower(): code for code, name in countries})

        d = defaultdict(list)
        for code, name in countries:
            k = name[:3].lower().strip()
            if k in self.countries_name or len(k) < 3:
                continue
            d[k].append(code)
        for k, v in d.items():
            if len(v) == 1:
                self.countries_name[k] = v[0]

        self.missed_countries = defaultdict(int)
        self.logger = getLogger('ranking.parse.countrier')

    def get(self, name):
        ret = self.countries_name.get(name.lower())
        if not ret:
            self.missed_countries[name] += 1
        return ret

    def __del__(self):
        if self.missed_countries:
            self.logger.warning(f'Missed countries = {self.missed_countries}')
