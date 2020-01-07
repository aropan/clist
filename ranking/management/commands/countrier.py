#!/usr/bin/env python3

from logging import getLogger

from django_countries import countries


class Countrier:

    def __init__(self):
        self.countries_name = {name.lower(): code for code, name in countries}
        self.countries_name.update({code.lower(): code for code, name in countries})
        self.countries_name.update({countries.alpha3(code).lower(): code for code, name in countries})
        self.missed_countries = set()
        self.logger = getLogger('ranking.parse.countrier')

    def get(self, name):
        ret = self.countries_name.get(name.lower())
        if not ret:
            self.missed_countries.add(name)
        return ret

    def __del__(self):
        if self.missed_countries:
            self.logger.warning(f'Missed countries = {self.missed_countries}')
