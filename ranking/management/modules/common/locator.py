#!/usr/bin/env python3

import os

import yaml
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter


class Locator:

    def __init__(
        self,
        locations_file=os.path.join(os.path.dirname(__file__), '.locations.yaml')
    ):
        self.locations_file = locations_file
        geolocator = Nominatim(user_agent="clist.by", timeout=5)
        self.geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1, max_retries=3)

    def get_country(self, location):
        if not location:
            return
        if location not in self.locations or 'en' not in (self.locations[location] or {}):
            try:
                self.locations.setdefault(location, {})['en'] = self.geocode(location, language='en').address
            except Exception:
                self.locations[location] = None

        address = self.locations[location]
        if not address:
            return
        *_, country = map(str.strip, address['en'].split(','))
        if country.startswith('The '):
            country = country[4:]
        return country

    def __enter__(self):
        self.locations = {}
        if os.path.exists(self.locations_file):
            with open(self.locations_file, 'r') as fo:
                data = yaml.safe_load(fo)
                self.locations = {k: v for k, v in data.items() if v}
        if self.locations is None:
            self.locations = {}
        return self

    def __exit__(self, *args, **kwargs):
        with open(self.locations_file, 'wb') as fo:
            yaml.dump(self.locations, fo, encoding='utf8', allow_unicode=True)
